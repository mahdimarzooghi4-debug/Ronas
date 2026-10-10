"""Revocation + audit + immutable case-version checks, synthetic records only."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import json
import time
import unittest

from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.keycloak import KeycloakConfig
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant
from ronas_api.scoped_audit import (
    AuditedSyntheticDraftRegistry, GrantConflict, GrantNotAuthorized,
)

ISSUER = "https://keycloak.example.test/realms/ronas"
API = "ronas-api"
BROWSER = "ronas-web"
DOM = "/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001"
EXP = "/api/v1/admin/export/research/drafts/DEMO-E-001"
OWN = "/api/v1/domestic/household-intake/drafts/DEMO-D-001"


def sample():
    records = (
        ScopedDraft(
            "DEMO-D-001", "DOMESTIC", "synthetic-household-001", 3,
            (ScopedGrant("synthetic-domestic-001", "domestic_ops"),
             ScopedGrant("synthetic-domestic-002", "domestic_ops")),
        ),
        ScopedDraft(
            "DEMO-E-001", "EXPORT", "synthetic-export-owner", 2,
            (ScopedGrant("synthetic-export-001", "export_ops"),),
            source_ref="DEMO-SOURCE-01",
        ),
    )
    earlier = (
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 1, ()),
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 2, ()),
        ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner", 1, (),
                    source_ref="DEMO-SOURCE-01"),
    )
    return records, earlier


def authoritative(actor, engine, ref):
    # Synthetic test fixture. NEVER a default admin or real role policy.
    return actor == "synthetic-grant-reviewer" and (engine, ref) in {
        ("DOMESTIC", "DEMO-D-001"), ("EXPORT", "DEMO-E-001")
    }


class AuditOverlayTests(unittest.TestCase):
    def setUp(self):
        records, history = sample()
        self.registry = AuditedSyntheticDraftRegistry(
            records, previous_versions=history,
            trusted_revoke_authorizer=authoritative,
        )
        self.domestic = Principal("synthetic-domestic-001", frozenset({"domestic_ops"}))
        self.domestic_other = Principal("synthetic-domestic-002", frozenset({"domestic_ops"}))
        self.household = Principal("synthetic-household-001", frozenset({"household"}))
        self.export = Principal("synthetic-export-001", frozenset({"export_ops"}))

    def revoke(self, *, engine="DOMESTIC", ref="DEMO-D-001",
               subject="synthetic-domestic-001", role="domestic_ops",
               actor="synthetic-grant-reviewer", expected_grant_revision=0,
               action_id="DEMO-ACTION-001", reason_ref="DEMO-REASON-001"):
        return self.registry.revoke_grant(
            engine=engine, ref=ref, subject=subject, role=role,
            actor=actor, expected_grant_revision=expected_grant_revision,
            action_id=action_id, reason_ref=reason_ref,
        )

    def test_revision_history_is_explicitly_seeded_and_immutable(self):
        self.assertEqual(self.registry.case_versions("DOMESTIC", "DEMO-D-001"), (1, 2, 3))
        self.assertEqual(self.registry.case_versions("EXPORT", "DEMO-E-001"), (1, 2))
        self.assertEqual(self.registry.case_versions("EXPORT", "DEMO-D-001"), ())
        before = self.registry.read("DOMESTIC", "DEMO-D-001", self.household, as_owner=True)
        self.assertEqual(before["version"], 3)
        before["version"] = 99
        self.assertEqual(
            self.registry.read("DOMESTIC", "DEMO-D-001", self.household,
                               as_owner=True)["version"], 3,
        )

    def test_revoke_is_immediately_enforced_for_existing_signed_role(self):
        self.assertIsNotNone(
            self.registry.read("DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False)
        )
        event = self.revoke()
        self.assertEqual(event.kind, "GRANT_REVOKED")
        self.assertEqual(event.grant_revision, 1)
        self.assertIsNone(
            self.registry.read("DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False)
        )
        self.assertEqual(self.registry.grant_revision("DOMESTIC", "DEMO-D-001"), 1)
        self.assertTrue(self.registry.verify_local_chain())

    def test_revocation_does_not_remove_other_grantee_or_household_owner(self):
        self.revoke()
        self.assertIsNotNone(self.registry.read(
            "DOMESTIC", "DEMO-D-001", self.domestic_other, as_owner=False
        ))
        self.assertIsNotNone(self.registry.read(
            "DOMESTIC", "DEMO-D-001", self.household, as_owner=True
        ))
        self.assertIsNotNone(self.registry.read(
            "EXPORT", "DEMO-E-001", self.export, as_owner=False
        ))
        self.assertEqual(self.registry.grant_revision("EXPORT", "DEMO-E-001"), 0)

    def test_export_revoke_cannot_affect_domestic(self):
        event = self.revoke(
            engine="EXPORT", ref="DEMO-E-001",
            subject="synthetic-export-001", role="export_ops",
            action_id="DEMO-ACTION-E-001",
        )
        self.assertEqual(event.engine, "EXPORT")
        self.assertIsNone(self.registry.read(
            "EXPORT", "DEMO-E-001", self.export, as_owner=False
        ))
        self.assertIsNotNone(self.registry.read(
            "DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False
        ))

    def test_reason_action_and_grant_revision_are_compared_exactly(self):
        result = self.revoke()
        first_len = len(self.registry.audit_snapshot())
        retry = self.revoke()
        self.assertIs(retry, result)
        self.assertEqual(len(self.registry.audit_snapshot()), first_len)
        with self.assertRaises(GrantConflict):
            self.revoke(reason_ref="DEMO-REASON-CHANGED")
        with self.assertRaises(GrantConflict):
            self.revoke(action_id="DEMO-ACTION-NEW", expected_grant_revision=0)
        with self.assertRaises(GrantConflict):
            self.revoke(action_id="DEMO-ACTION-NEW", expected_grant_revision=1)
        self.assertEqual(self.registry.grant_revision("DOMESTIC", "DEMO-D-001"), 1)

    def test_failed_audit_append_rolls_back_revoke_without_half_state(self):
        original = self.registry._event
        def fail_write(**kwargs):
            raise RuntimeError("synthetic audit failure")
        self.registry._event = fail_write
        with self.assertRaisesRegex(RuntimeError, "audit failure"):
            self.revoke()
        self.assertEqual(self.registry.grant_revision("DOMESTIC", "DEMO-D-001"), 0)
        self.assertEqual(self.registry.audit_snapshot(), ())
        self.registry._event = original
        self.assertIsNotNone(self.registry.read(
            "DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False
        ))
        self.revoke()
        self.assertIsNone(self.registry.read(
            "DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False
        ))
        self.assertTrue(self.registry.verify_local_chain())

    def test_second_distinct_revocation_has_strict_compare_and_swap(self):
        self.revoke()
        with self.assertRaises(GrantConflict):
            self.revoke(subject="synthetic-domestic-002", action_id="DEMO-ACTION-002")
        second = self.revoke(subject="synthetic-domestic-002",
                             action_id="DEMO-ACTION-002", expected_grant_revision=1)
        self.assertEqual(second.grant_revision, 2)
        self.assertIsNone(self.registry.read(
            "DOMESTIC", "DEMO-D-001", self.domestic_other, as_owner=False
        ))

    def test_authority_is_independent_from_jwt_governance_and_role(self):
        with self.assertRaises(GrantNotAuthorized):
            self.revoke(actor="synthetic-domestic-001")
        with self.assertRaises(GrantNotAuthorized):
            self.revoke(actor="synthetic-governance-001")
        self.assertEqual(self.registry.grant_revision("DOMESTIC", "DEMO-D-001"), 0)
        records, history = sample()
        denied = AuditedSyntheticDraftRegistry(
            records, previous_versions=history,
            trusted_revoke_authorizer=lambda actor, engine, ref: False,
        )
        with self.assertRaises(GrantNotAuthorized):
            denied.revoke_grant(
                engine="DOMESTIC", ref="DEMO-D-001",
                subject="synthetic-domestic-001", role="domestic_ops",
                actor="synthetic-grant-reviewer", expected_grant_revision=0,
                action_id="DEMO-ACTION-003", reason_ref="DEMO-REASON-001",
            )

    def test_duplicate_missing_wrong_engine_role_or_unseeded_revoke_fails_closed(self):
        for changes in (
            {"engine": "EXPORT"},
            {"role": "export_ops"},
            {"subject": "synthetic-not-assigned"},
            {"actor": "unverified-real-person"},
            {"ref": "DEMO-NOT-FOUND"},
            {"action_id": "invalid"},
            {"reason_ref": ""},
            {"expected_grant_revision": True},
            {"expected_grant_revision": -1},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises((ValueError, GrantConflict)):
                    self.revoke(**changes)
        self.assertEqual(len(self.registry.audit_snapshot()), 0)

    def test_read_audit_records_allowed_denied_and_mode_without_raw_subjects(self):
        self.assertIsNotNone(self.registry.read(
            "DOMESTIC", "DEMO-D-001", self.household, as_owner=True
        ))
        self.assertIsNone(self.registry.read(
            "DOMESTIC", "DEMO-D-001", self.export, as_owner=False
        ))
        events = self.registry.audit_snapshot()
        self.assertEqual([x.kind for x in events], ["READ_ALLOWED", "READ_DENIED"])
        self.assertEqual([x.access_mode for x in events], ["OWNER", "OPERATIONS"])
        self.assertTrue(self.registry.verify_local_chain())
        raw = json.dumps([repr(e) for e in events])
        self.assertNotIn("synthetic-household-001", raw)
        self.assertNotIn("synthetic-export-001", raw)
        self.assertNotIn("Bearer ", raw)
        self.assertTrue(all(len(e.actor_digest) == 64 for e in events))
        with self.assertRaises(FrozenInstanceError):
            events[0].kind = "READ_ALLOWED_BYPASS"

    def test_audit_chain_links_revoke_and_access_and_detects_local_tampering(self):
        self.registry.read("DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False)
        self.revoke()
        self.registry.read("DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False)
        events = self.registry.audit_snapshot()
        self.assertEqual([e.kind for e in events],
                         ["READ_ALLOWED", "GRANT_REVOKED", "READ_DENIED"])
        self.assertEqual([e.sequence for e in events], [1, 2, 3])
        self.assertEqual(events[1].previous_digest, events[0].digest)
        self.assertEqual(events[2].previous_digest, events[1].digest)
        self.assertTrue(self.registry.verify_local_chain())
        # Artificial privileged corruption for test only.
        object.__setattr__(self.registry._events[0], "kind", "TAMPERED")
        self.assertFalse(self.registry.verify_local_chain())

    def test_bad_seed_revision_owner_and_duplicate_versions_are_rejected(self):
        records, history = sample()
        for old in (
            ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 3, ()),
            ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-wrong-owner", 1, ()),
            ScopedDraft("DEMO-UNKNOWN", "DOMESTIC", "synthetic-household-001", 1, ()),
        ):
            with self.subTest(old=old):
                with self.assertRaises(ValueError):
                    AuditedSyntheticDraftRegistry(
                        records, previous_versions=(old,),
                        trusted_revoke_authorizer=authoritative,
                    )
        with self.assertRaises(ValueError):
            AuditedSyntheticDraftRegistry(
                records, previous_versions=(history[0], history[0]),
                trusted_revoke_authorizer=authoritative,
            )
        with self.assertRaises(ValueError):
            AuditedSyntheticDraftRegistry(records, trusted_revoke_authorizer=None)

    def test_concurrent_duplicate_revoke_is_exactly_once(self):
        from threading import Barrier
        barrier = Barrier(10)

        def attempt(_):
            barrier.wait(timeout=10)
            return self.revoke()

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(attempt, range(10)))
        self.assertTrue(all(x is results[0] for x in results))
        self.assertEqual(self.registry.grant_revision("DOMESTIC", "DEMO-D-001"), 1)
        self.assertEqual([e.kind for e in self.registry.audit_snapshot()], ["GRANT_REVOKED"])
        self.assertTrue(self.registry.verify_local_chain())

    def test_concurrent_distinct_revoke_rejects_stale_revision(self):
        from threading import Barrier
        barrier = Barrier(2)

        def attempt(n):
            barrier.wait(timeout=10)
            try:
                self.revoke(subject="synthetic-domestic-00" + str(n),
                            action_id="DEMO-ACTION-" + str(n),
                            expected_grant_revision=0)
                return "ok"
            except GrantConflict:
                return "stale"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, (1, 2)))
        self.assertCountEqual(outcomes, ["ok", "stale"])
        self.assertEqual(self.registry.grant_revision("DOMESTIC", "DEMO-D-001"), 1)


class HTTPRevocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.private.public_key()))
        jwk.update({"kid": "key-1", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(
            ISSUER, API, BROWSER, json.dumps({"keys": [jwk]}).encode(),
        )

    def setUp(self):
        records, history = sample()
        self.registry = AuditedSyntheticDraftRegistry(
            records, previous_versions=history,
            trusted_revoke_authorizer=authoritative,
        )
        self.client = TestClient(create_app(self.config, scoped_registry=self.registry))

    def headers(self, subject, roles):
        now = int(time.time())
        token = jwt.encode({
            "iss": ISSUER, "aud": [API], "sub": subject, "azp": BROWSER,
            "typ": "Bearer", "iat": now - 10, "nbf": now - 10, "exp": now + 600,
            "resource_access": {API: {"roles": roles}},
        }, self.private, algorithm="RS256", headers={"kid": "key-1"})
        return {"Authorization": "Bearer " + token}

    def test_old_valid_jwt_loses_case_read_immediately_after_revoke(self):
        headers = self.headers("synthetic-domestic-001", ["domestic_ops", "governance"])
        self.assertEqual(self.client.get(DOM, headers=headers).status_code, 200)
        self.registry.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject="synthetic-domestic-001", role="domestic_ops",
            actor="synthetic-grant-reviewer", expected_grant_revision=0,
            action_id="DEMO-ACTION-HTTP", reason_ref="DEMO-REASON-HTTP",
        )
        response = self.client.get(DOM, headers=headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "DRAFT_NOT_FOUND")
        self.assertEqual(self.client.get(DOM, headers=self.headers(
            "synthetic-domestic-002", ["domestic_ops"],
        )).status_code, 200)
        self.assertEqual(self.client.get(OWN, headers=self.headers(
            "synthetic-household-001", ["household"]
        )).status_code, 200)

    def test_revoke_endpoint_and_audit_export_not_exposed_over_http(self):
        h = self.headers("synthetic-domestic-001", ["domestic_ops", "governance"])
        for route in ("/api/v1/record-grants/revoke", "/api/v1/admin/audit",
                      "/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001/revoke"):
            self.assertEqual(self.client.post(route, headers=h, json={}).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/admin/audit", headers=h).status_code, 404)
        self.assertEqual(self.client.post(DOM, headers=h, json={}).status_code, 405)

    def test_missing_signed_identity_cannot_produce_authenticated_read(self):
        self.assertEqual(self.client.get(DOM).status_code, 401)
        self.assertEqual(self.registry.audit_snapshot(), ())


if __name__ == "__main__":
    unittest.main()
