"""Durable SQLite case-grant ledger: offline recovery, races, atomic audit, isolation."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
import json
import secrets
import sqlite3
import tempfile
from threading import Barrier
import time
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from ronas_api.app import create_app
from ronas_api.auth import Principal
from ronas_api.grant_ledger_sqlite import (
    LedgerIntegrityError, SqliteSyntheticGrantLedger,
    REVOCATION_COMMAND_MODE, _hash, _json,
)
from ronas_api.keycloak import KeycloakConfig
from ronas_api.scoped_audit import AuditEntry, GrantConflict, GrantNotAuthorized
from ronas_api.scoped_drafts import ScopedDraft, ScopedGrant

ISSUER = "https://id.example.test/realms/ronas"
API, BROWSER = "ronas-api", "ronas-web"
DOM_PATH = "/api/v1/admin/domestic/household-intake/drafts/DEMO-D-001"
EXPORT_PATH = "/api/v1/admin/export/research/drafts/DEMO-E-001"
OWNER_PATH = "/api/v1/domestic/household-intake/drafts/DEMO-D-001"


def records():
    return (
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 3, (
            ScopedGrant("synthetic-domestic-001", "domestic_ops"),
            ScopedGrant("synthetic-domestic-002", "domestic_ops"),
        )),
        ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner-001", 2, (
            ScopedGrant("synthetic-export-001", "export_ops"),
        ), source_ref="DEMO-SOURCE-01"),
    )


def history():
    return (
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 1, ()),
        ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 2, ()),
        ScopedDraft("DEMO-E-001", "EXPORT", "synthetic-export-owner-001", 1, (),
                    source_ref="DEMO-SOURCE-01"),
    )


def authorized(actor, engine, ref):
    # Only a synthetic test fixture, never Production role policy.
    return actor == "synthetic-revocation-controller" and (engine, ref) in {
        ("DOMESTIC", "DEMO-D-001"), ("EXPORT", "DEMO-E-001"),
    }


class PersistentGrantLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "scope-audit.db"
        self.ledger = self.open()
        self.domestic = Principal("synthetic-domestic-001", frozenset({"domestic_ops"}))
        self.other = Principal("synthetic-domestic-002", frozenset({"domestic_ops"}))
        self.household = Principal("synthetic-household-001", frozenset({"household"}))
        self.export = Principal("synthetic-export-001", frozenset({"export_ops"}))

    def open(self, *, allow=authorized):
        return SqliteSyntheticGrantLedger(
            self.path, records(), previous_versions=history(),
            trusted_revoke_authorizer=allow,
        )

    def revoke(self, ledger=None, **change):
        request = {
            "engine": "DOMESTIC", "ref": "DEMO-D-001",
            "subject": "synthetic-domestic-001", "role": "domestic_ops",
            "actor": "synthetic-revocation-controller", "expected_grant_revision": 0,
            "action_id": "DEMO-ACTION-D-001", "reason_ref": "DEMO-REASON-D-001",
        }
        request.update(change)
        return (ledger or self.ledger).revoke_grant(**request)

    def test_persistent_versions_and_private_file(self):
        self.assertEqual(self.ledger.case_versions("DOMESTIC", "DEMO-D-001"), (1, 2, 3))
        self.assertEqual(self.ledger.case_versions("EXPORT", "DEMO-E-001"), (1, 2))
        self.assertEqual(self.ledger.case_versions("EXPORT", "DEMO-D-001"), ())
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)
        reopened = self.open()
        self.assertEqual(reopened.case_versions("DOMESTIC", "DEMO-D-001"), (1, 2, 3))
        self.assertTrue(reopened.verify_integrity())

    def test_post_restart_revocation_denies_old_role_and_preserves_others(self):
        self.assertIsNotNone(self.ledger.read(
            "DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False
        ))
        result = self.revoke()
        self.assertEqual(result.kind, "GRANT_REVOKED")
        reopened = self.open()
        self.assertIsNone(reopened.read(
            "DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False
        ))
        self.assertIsNotNone(reopened.read(
            "DOMESTIC", "DEMO-D-001", self.other, as_owner=False
        ))
        self.assertIsNotNone(reopened.read(
            "DOMESTIC", "DEMO-D-001", self.household, as_owner=True
        ))
        self.assertIsNotNone(reopened.read(
            "EXPORT", "DEMO-E-001", self.export, as_owner=False
        ))
        self.assertEqual(reopened.grant_revision("DOMESTIC", "DEMO-D-001"), 1)
        self.assertEqual(reopened.grant_revision("EXPORT", "DEMO-E-001"), 0)

    def test_persistent_audit_chain_and_no_plaintext_subjects(self):
        self.ledger.read("DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False)
        self.revoke()
        self.ledger.read("DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False)
        reopened = self.open()
        events = reopened.audit_snapshot()
        self.assertEqual([x.kind for x in events],
                         ["READ_ALLOWED", "GRANT_REVOKED", "READ_DENIED"])
        self.assertEqual([x.sequence for x in events], [1, 2, 3])
        self.assertEqual(events[1].previous_digest, events[0].digest)
        self.assertEqual(events[2].previous_digest, events[1].digest)
        self.assertTrue(reopened.verify_integrity())
        with sqlite3.connect(self.path) as db:
            flat = "".join(str(row) for row in db.execute(
                "SELECT payload FROM audit_event"
            ))
            flat += str(list(db.execute("SELECT * FROM grant_revocation")))
        self.assertNotIn("synthetic-domestic-001", flat)
        self.assertNotIn("synthetic-revocation-controller", flat)
        self.assertNotIn("Bearer ", flat)

    def test_identical_action_idempotent_across_restart_and_changed_payload_denied(self):
        original = self.revoke()
        second = self.revoke(self.open())
        self.assertEqual(original, second)
        self.assertEqual(self.open().grant_revision("DOMESTIC", "DEMO-D-001"), 1)
        self.assertEqual(len(self.open().audit_snapshot()), 1)
        with self.assertRaises(GrantConflict):
            self.revoke(self.open(), reason_ref="DEMO-REASON-CHANGED")
        # Independent authorization is checked before replay identity,
        # so an untrusted actor receives NOT AUTHORIZED, not replay details.
        with self.assertRaises(GrantNotAuthorized):
            self.revoke(self.open(), actor="synthetic-unauthorized-person")

    def test_two_independent_db_connections_serialize_distinct_revocations(self):
        barrier = Barrier(2)
        def attempt(n):
            instance = self.open()
            barrier.wait(timeout=8)
            try:
                self.revoke(instance, subject="synthetic-domestic-00" + str(n),
                            action_id="DEMO-ACTION-D-00" + str(n))
                return "accepted"
            except GrantConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(attempt, (1, 2)))
        self.assertCountEqual(result, ["accepted", "conflict"])
        self.assertEqual(self.open().grant_revision("DOMESTIC", "DEMO-D-001"), 1)
        self.assertEqual([e.kind for e in self.open().audit_snapshot()], ["GRANT_REVOKED"])

    def test_eight_concurrent_identical_revoke_exactly_one_event(self):
        barrier = Barrier(8)
        def attempt(_):
            instance = self.open()
            barrier.wait(timeout=12)
            return self.revoke(instance)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(len({event.digest for event in results}), 1)
        self.assertEqual(self.open().grant_revision("DOMESTIC", "DEMO-D-001"), 1)
        self.assertEqual(len(self.open().audit_snapshot()), 1)

    def test_export_revoke_independent_from_domestic(self):
        self.revoke(engine="EXPORT", ref="DEMO-E-001",
                    subject="synthetic-export-001", role="export_ops",
                    action_id="DEMO-ACTION-E-001", reason_ref="DEMO-REASON-E-001")
        reopened = self.open()
        self.assertIsNone(reopened.read(
            "EXPORT", "DEMO-E-001", self.export, as_owner=False
        ))
        self.assertIsNotNone(reopened.read(
            "DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False
        ))
        self.assertEqual(reopened.grant_revision("EXPORT", "DEMO-E-001"), 1)
        self.assertEqual(reopened.grant_revision("DOMESTIC", "DEMO-D-001"), 0)

    def test_missing_authority_no_audit_and_no_change(self):
        with self.assertRaises(GrantNotAuthorized):
            self.revoke(actor="synthetic-governance-001")
        with self.assertRaises(GrantNotAuthorized):
            self.revoke(self.open(allow=lambda actor, engine, ref: False))
        self.assertEqual(self.open().audit_snapshot(), ())
        self.assertEqual(self.open().grant_revision("DOMESTIC", "DEMO-D-001"), 0)

    def test_failed_audit_insert_rolls_back_grant_and_revision(self):
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TRIGGER reject_new_event BEFORE INSERT ON audit_event
                BEGIN SELECT RAISE(ABORT, 'synthetic audit unavailable'); END;""")
        with self.assertRaises(sqlite3.DatabaseError):
            self.revoke()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER reject_new_event")
        reopened = self.open()
        self.assertEqual(reopened.audit_snapshot(), ())
        self.assertEqual(reopened.grant_revision("DOMESTIC", "DEMO-D-001"), 0)
        self.assertIsNotNone(reopened.read(
            "DOMESTIC", "DEMO-D-001", self.domestic, as_owner=False
        ))

    def test_trigger_protects_append_only_history(self):
        self.revoke()
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM audit_event")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE audit_event SET digest='wrong'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM grant_revocation")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM case_history")
        self.assertTrue(self.open().verify_integrity())

    def test_tampered_head_or_revision_blocks_reopen_and_access(self):
        self.revoke()
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE metadata SET value=? WHERE key='head_digest'",
                ("f" * 64,),
            )
        self.assertFalse(self.ledger.verify_integrity())
        with self.assertRaises(LedgerIntegrityError):
            self.open()
        with self.assertRaises(LedgerIntegrityError):
            self.ledger.read("DOMESTIC", "DEMO-D-001",
                             self.domestic, as_owner=False)

    def test_revocation_payload_is_attested_in_audit_event(self):
        event = self.revoke()
        with sqlite3.connect(self.path) as db:
            payload, subject_hash = db.execute(
                "SELECT payload_digest, subject_digest FROM grant_revocation"
            ).fetchone()
        self.assertEqual(event.access_mode, REVOCATION_COMMAND_MODE + payload)
        self.assertEqual(event.target_digest, subject_hash)
        self.assertEqual(self.open().audit_snapshot()[0], event)
        self.assertTrue(self.open().verify_integrity())

    def test_corrupted_revocation_payload_digest_fails_closed(self):
        self.revoke()
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER revocation_no_update")
            db.execute(
                "UPDATE grant_revocation SET payload_digest=?",
                ("f" * 64,),
            )
        self.assertFalse(self.ledger.verify_integrity())
        with self.assertRaises(LedgerIntegrityError):
            self.open()
        with self.assertRaises(LedgerIntegrityError):
            self.ledger.read("DOMESTIC", "DEMO-D-001",
                             self.other, as_owner=False)

    def test_legacy_unbound_revocation_cannot_be_silently_admitted(self):
        # Simulate an older local-only row with no command binding. An old
        # unauthenticated digest cannot safely be "upgraded" on read.
        with self.ledger._transaction() as db:
            db.execute(
                "UPDATE case_revision SET revision=1 WHERE engine=? AND ref=?",
                ("DOMESTIC", "DEMO-D-001"),
            )
            event = self.ledger._append(
                db, kind="GRANT_REVOKED", engine="DOMESTIC", ref="DEMO-D-001",
                actor="synthetic-revocation-controller",
                target="synthetic-domestic-001",
                action_id="DEMO-OLD-ACTION", reason_ref="DEMO-REASON-OLD",
                mode=None,
            )
            db.execute(
                "INSERT INTO grant_revocation VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("DEMO-OLD-ACTION", "DOMESTIC", "DEMO-D-001",
                 _hash("synthetic-domestic-001"), "domestic_ops",
                 "a" * 64, event.sequence),
            )
        with self.assertRaises(LedgerIntegrityError):
            self.open()
        self.assertFalse(self.ledger.verify_integrity())

    def test_rebased_read_audit_revision_must_match_case_lineage(self):
        self.ledger.read("DOMESTIC", "DEMO-D-001",
                         self.domestic, as_owner=False)
        with sqlite3.connect(self.path) as db:
            payload = db.execute(
                "SELECT payload FROM audit_event WHERE sequence=1"
            ).fetchone()[0]
            original = AuditEntry(**json.loads(payload))
            forged = replace(original, grant_revision=1, digest="")
            forged = replace(forged, digest=_hash(forged.canonical().decode()))
            db.execute("DROP TRIGGER audit_no_update")
            db.execute(
                "UPDATE audit_event SET digest=?, payload=? WHERE sequence=1",
                (forged.digest, _json(asdict(forged))),
            )
            db.execute(
                "UPDATE metadata SET value=? WHERE key='head_digest'",
                (forged.digest,),
            )
        with self.assertRaises(LedgerIntegrityError):
            self.open()
        self.assertFalse(self.ledger.verify_integrity())

    def test_audited_revocation_of_nonseeded_grantee_fails_closed(self):
        # Even if a local actor forges a self-consistent row and audit
        # event, the target must still be in the immutable seeded grants.
        with self.ledger._transaction() as db:
            db.execute(
                "UPDATE case_revision SET revision=1 WHERE engine=? AND ref=?",
                ("DOMESTIC", "DEMO-D-001"),
            )
            event = self.ledger._append(
                db, kind="GRANT_REVOKED", engine="DOMESTIC", ref="DEMO-D-001",
                actor="synthetic-revocation-controller",
                target="synthetic-stranger-001",
                action_id="DEMO-UNKNOWN-TARGET",
                reason_ref="DEMO-UNKNOWN-REASON",
                mode=REVOCATION_COMMAND_MODE + "a" * 64,
            )
            db.execute(
                "INSERT INTO grant_revocation VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("DEMO-UNKNOWN-TARGET", "DOMESTIC", "DEMO-D-001",
                 _hash("synthetic-stranger-001"), "domestic_ops",
                 "a" * 64, event.sequence),
            )
        with self.assertRaises(LedgerIntegrityError):
            self.open()

    def test_seed_drift_does_not_silently_rebind_existing_grants(self):
        with self.assertRaises(LedgerIntegrityError):
            SqliteSyntheticGrantLedger(
                self.path, (
                    ScopedDraft("DEMO-D-001", "DOMESTIC", "synthetic-household-001", 4,
                                (ScopedGrant("synthetic-domestic-001", "domestic_ops"),)),
                ), trusted_revoke_authorizer=authorized,
            )
        self.assertTrue(self.open().verify_integrity())

    def test_private_regular_file_and_explicit_authorizer(self):
        with self.assertRaises(ValueError):
            SqliteSyntheticGrantLedger("relative.sqlite", records(),
                                       trusted_revoke_authorizer=authorized)
        with self.assertRaises(ValueError):
            SqliteSyntheticGrantLedger(self.path, records(),
                                       trusted_revoke_authorizer=None)
        symlink = Path(self.tmp.name) / "linked.db"
        symlink.symlink_to(self.path)
        with self.assertRaises(ValueError):
            SqliteSyntheticGrantLedger(symlink, records(),
                                       trusted_revoke_authorizer=authorized)


class SignedAPIRevocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(cls.private.public_key()))
        jwk.update({"kid": "test-001", "alg": "RS256", "use": "sig"})
        cls.config = KeycloakConfig(
            ISSUER, API, BROWSER, json.dumps({"keys": [jwk]}).encode()
        )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "audit.db"
        self.ledger = SqliteSyntheticGrantLedger(
            self.path, records(), previous_versions=history(),
            trusted_revoke_authorizer=authorized,
        )
        self.client = TestClient(create_app(self.config, scoped_registry=self.ledger))

    def headers(self, subject, roles):
        now = int(time.time())
        token = jwt.encode({
            "iss": ISSUER, "aud": API, "sub": subject, "azp": BROWSER,
            "typ": "Bearer", "iat": now - 5, "nbf": now - 5, "exp": now + 600,
            "resource_access": {API: {"roles": roles}},
        }, self.private, algorithm="RS256", headers={"kid": "test-001"})
        return {"Authorization": "Bearer " + token}

    def test_valid_keycloak_token_denied_after_durable_revocation(self):
        headers = self.headers("synthetic-domestic-001",
                               ["domestic_ops", "governance"])
        self.assertEqual(self.client.get(DOM_PATH, headers=headers).status_code, 200)
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject="synthetic-domestic-001", role="domestic_ops",
            actor="synthetic-revocation-controller",
            expected_grant_revision=0, action_id="DEMO-ACTION-D-001",
            reason_ref="DEMO-REASON-D-001",
        )
        self.assertEqual(self.client.get(DOM_PATH, headers=headers).status_code, 404)
        self.assertEqual(TestClient(create_app(
            self.config, scoped_registry=SqliteSyntheticGrantLedger(
                self.path, records(), previous_versions=history(),
                trusted_revoke_authorizer=authorized,
            ),
        )).get(DOM_PATH, headers=headers).status_code, 404)
        self.assertEqual(self.client.get(DOM_PATH, headers=self.headers(
            "synthetic-domestic-002", ["domestic_ops"],
        )).status_code, 200)
        self.assertEqual(self.client.get(OWNER_PATH, headers=self.headers(
            "synthetic-household-001", ["household"],
        )).status_code, 200)

    def test_tampered_revocation_returns_503_not_untrusted_draft(self):
        self.ledger.revoke_grant(
            engine="DOMESTIC", ref="DEMO-D-001",
            subject="synthetic-domestic-001", role="domestic_ops",
            actor="synthetic-revocation-controller",
            expected_grant_revision=0,
            action_id="DEMO-ACTION-D-001",
            reason_ref="DEMO-REASON-D-001",
        )
        with sqlite3.connect(self.path) as db:
            db.execute("DROP TRIGGER revocation_no_update")
            db.execute("UPDATE grant_revocation SET payload_digest=?", ("f" * 64,))
        headers = self.headers("synthetic-domestic-002", ["domestic_ops"])
        response = self.client.get(DOM_PATH, headers=headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "SYNTHETIC_LEDGER_UNAVAILABLE"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("DEMO-REASON-D-001", response.text)

    def test_no_public_write_or_audit_exposure(self):
        headers = self.headers("synthetic-domestic-001",
                               ["domestic_ops", "governance"])
        self.assertEqual(self.client.post(
            "/api/v1/grant-revocations", headers=headers, json={}
        ).status_code, 404)
        self.assertEqual(self.client.get(
            "/api/v1/admin/audit", headers=headers
        ).status_code, 404)
        self.assertEqual(self.client.post(
            DOM_PATH, headers=headers, json={"status": "APPROVED"}
        ).status_code, 405)
        self.assertEqual(TestClient(create_app(self.config)).get(
            DOM_PATH, headers=headers
        ).status_code, 404)


if __name__ == "__main__":
    unittest.main()
