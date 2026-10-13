import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ronas_api.auth import Principal
from ronas_api.domestic_surplus_publication import (
    OfferRevision, PublicationAttestation, PublicationAuthorities,
    evaluate_surplus_publication,
)
from ronas_api.domestic_surplus_publication_api import (
    build_domestic_surplus_publication_router,
)

D = "a" * 64
E = "b" * 64
F = "c" * 64


def offer(revision=1, digest=D):
    return OfferRevision("DEMO-OFFER-01", "DEMO-H-01",
                         "producer-01", revision, digest)


def approvals(target=None):
    target = target or offer()
    return (
        PublicationAttestation(
            "producer-approval-01", target.offer_ref, target.revision,
            target.payload_digest, "PRODUCER", target.producer_subject,
            E, True, True,
        ),
        PublicationAttestation(
            "quality-check-01", target.offer_ref, target.revision,
            target.payload_digest, "QUALITY_SAFETY", "quality-authority-01",
            F, True, True,
        ),
    )


class DomesticSurplusPublicationTests(unittest.TestCase):
    def test_default_gates_keep_offer_non_public(self):
        result = evaluate_surplus_publication(offer(), PublicationAuthorities())
        self.assertEqual(result.state, "NON_PUBLIC_DRAFT")
        self.assertFalse(result.can_publish)
        self.assertFalse(result.published)
        self.assertEqual(set(result.blockers), {
            "CURRENT_OFFER_UNAVAILABLE", "PRODUCER_APPROVAL_REQUIRED",
            "QUALITY_SAFETY_VERIFICATION_REQUIRED",
            "SELLER_ELIGIBILITY_UNVERIFIED", "HOUSEHOLD_PERMISSION_INACTIVE",
            "MARKETPLACE_GATE_CLOSED",
        })

    def test_both_version_bound_approvals_and_all_external_gates_required(self):
        current = offer()
        producer, quality = approvals(current)
        authorities = PublicationAuthorities(
            current_offer=current, producer_approval=producer,
            quality_safety_verification=quality,
            seller_eligibility_verified=True,
            household_permission_active=True, marketplace_gate_open=True,
        )
        result = evaluate_surplus_publication(current, authorities)
        self.assertTrue(result.can_publish)
        self.assertFalse(result.published)
        self.assertEqual(result.state, "PUBLICATION_AUTHORIZED")
        self.assertEqual(result.blockers, ())
        self.assertEqual(len(result.readiness_digest), 64)

    def test_revision_or_digest_change_invalidates_both_old_attestations(self):
        current = offer()
        producer, quality = approvals(current)
        revised = offer(revision=2, digest="9" * 64)
        authorities = PublicationAuthorities(
            current_offer=revised, producer_approval=producer,
            quality_safety_verification=quality,
            seller_eligibility_verified=True,
            household_permission_active=True, marketplace_gate_open=True,
        )
        result = evaluate_surplus_publication(current, authorities)
        self.assertFalse(result.can_publish)
        self.assertIn("OFFER_VERSION_CHANGED", result.blockers)
        self.assertIn("PRODUCER_APPROVAL_STALE", result.blockers)
        self.assertIn("QUALITY_SAFETY_VERIFICATION_STALE", result.blockers)

    def test_rejects_wrong_producer_or_same_actor_quality_attestation(self):
        current = offer()
        producer, quality = approvals(current)
        for producer_attestation, quality_attestation in (
            (PublicationAttestation(
                producer.attestation_ref, producer.offer_ref,
                producer.offer_revision, producer.payload_digest, "PRODUCER",
                "other-producer", E, True, True,
            ), quality),
            (producer, PublicationAttestation(
                quality.attestation_ref, quality.offer_ref,
                quality.offer_revision, quality.payload_digest, "QUALITY_SAFETY",
                current.producer_subject, F, True, True,
            )),
        ):
            result = evaluate_surplus_publication(current, PublicationAuthorities(
                current_offer=current, producer_approval=producer_attestation,
                quality_safety_verification=quality_attestation,
                seller_eligibility_verified=True,
                household_permission_active=True, marketplace_gate_open=True,
            ))
            self.assertFalse(result.can_publish)

    def test_rejected_or_unverified_attestation_fails_closed(self):
        current = offer()
        producer, quality = approvals(current)
        for accepted, verified in ((False, True), (True, False)):
            result = evaluate_surplus_publication(current, PublicationAuthorities(
                current_offer=current,
                producer_approval=PublicationAttestation(
                    producer.attestation_ref, producer.offer_ref,
                    producer.offer_revision, producer.payload_digest, "PRODUCER",
                    producer.authority_subject, E, accepted, verified,
                ),
                quality_safety_verification=quality,
                seller_eligibility_verified=True,
                household_permission_active=True, marketplace_gate_open=True,
            ))
            self.assertFalse(result.can_publish)
            self.assertTrue(result.blockers)

    def test_each_external_gate_blocks_publication_independently(self):
        current = offer()
        producer, quality = approvals(current)
        for field in ("seller_eligibility_verified",
                      "household_permission_active", "marketplace_gate_open"):
            values = dict(
                current_offer=current, producer_approval=producer,
                quality_safety_verification=quality,
                seller_eligibility_verified=True,
                household_permission_active=True, marketplace_gate_open=True,
            )
            values[field] = False
            result = evaluate_surplus_publication(
                current, PublicationAuthorities(**values),
            )
            self.assertFalse(result.can_publish)
            self.assertTrue(result.blockers)

    def test_readiness_projection_never_claims_published_or_real_data(self):
        payload = evaluate_surplus_publication(
            offer(), PublicationAuthorities(),
        ).as_dict()
        self.assertIs(payload["published"], False)
        self.assertIs(payload["real_data"], False)
        self.assertNotIn("authority_subject", payload)
        self.assertNotIn("evidence_digest", payload)

    def test_authority_inputs_require_strict_boolean_values(self):
        with self.assertRaises(ValueError):
            PublicationAuthorities(marketplace_gate_open=1)

    def test_offer_payload_rejects_bad_digest_and_boolean_revision(self):
        for revision, digest in ((True, D), (0, D), (1, "private text")):
            with self.subTest(revision=revision, digest=digest), self.assertRaises(ValueError):
                OfferRevision("DEMO-OFFER-01", "DEMO-H-01",
                              "producer-01", revision, digest)

    def test_wrong_quality_attestation_kind_fails_closed(self):
        current = offer()
        producer, quality = approvals(current)
        wrong = PublicationAttestation(
            quality.attestation_ref, quality.offer_ref, quality.offer_revision,
            quality.payload_digest, "PRODUCER", quality.authority_subject,
            F, True, True,
        )
        result = evaluate_surplus_publication(current, PublicationAuthorities(
            current_offer=current, producer_approval=producer,
            quality_safety_verification=wrong,
            seller_eligibility_verified=True,
            household_permission_active=True, marketplace_gate_open=True,
        ))
        self.assertFalse(result.can_publish)
        self.assertIn("QUALITY_SAFETY_VERIFICATION_STALE", result.blockers)

    def test_owner_route_hides_wrong_role_and_cross_household_offer(self):
        principal = [Principal("producer-01", frozenset({"household"}))]
        current = offer()
        producer, quality = approvals(current)
        resolved = [(
            current, PublicationAuthorities(
                current_offer=current, producer_approval=producer,
                quality_safety_verification=quality,
            ),
        )]
        calls = []
        def authority(identity, household_ref, offer_ref):
            calls.append((identity.subject, household_ref, offer_ref))
            return resolved[0]
        app = FastAPI()
        app.include_router(build_domestic_surplus_publication_router(
            authority, lambda: principal[0],
        ))
        client = TestClient(app)
        path = ("/api/v1/domestic/household-intake/my-drafts/DEMO-H-01/"
                "surplus-offers/DEMO-OFFER-01/publication-readiness")
        response = client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["can_publish"])
        self.assertFalse(response.json()["published"])
        self.assertEqual(len(calls), 1)
        principal[0] = Principal("ops-01", frozenset({"domestic_ops"}))
        self.assertEqual(client.get(path).status_code, 404)
        self.assertEqual(len(calls), 1)
        principal[0] = Principal("other-producer", frozenset({"household"}))
        self.assertEqual(client.get(path).status_code, 404)
        self.assertEqual(len(calls), 2)

    def test_readiness_digest_changes_when_authority_evidence_changes(self):
        current = offer()
        producer, quality = approvals(current)
        baseline = PublicationAuthorities(
            current_offer=current, producer_approval=producer,
            quality_safety_verification=quality,
            seller_eligibility_verified=True,
            household_permission_active=True, marketplace_gate_open=True,
        )
        revised = PublicationAuthorities(
            current_offer=current,
            producer_approval=PublicationAttestation(
                "producer-approval-02", current.offer_ref, current.revision,
                current.payload_digest, "PRODUCER", current.producer_subject,
                "9" * 64, True, True,
            ),
            quality_safety_verification=quality,
            seller_eligibility_verified=True,
            household_permission_active=True, marketplace_gate_open=True,
        )
        first = evaluate_surplus_publication(current, baseline)
        second = evaluate_surplus_publication(current, revised)
        self.assertTrue(first.can_publish and second.can_publish)
        self.assertNotEqual(first.readiness_digest, second.readiness_digest)

    def test_invalid_paths_are_rejected_before_authority_lookup(self):
        calls = []
        app = FastAPI()
        app.include_router(build_domestic_surplus_publication_router(
            lambda *args: calls.append(args),  # must not be reached
            lambda: Principal("producer-01", frozenset({"household"})),
        ))
        path = ("/api/v1/domestic/household-intake/my-drafts/bad ref/"
                "surplus-offers/DEMO-OFFER-01/publication-readiness")
        response = TestClient(app).get(path)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(calls, [])

    def test_broken_authority_fails_closed_without_leaking_error(self):
        app = FastAPI()
        app.include_router(build_domestic_surplus_publication_router(
            lambda *_: (_ for _ in ()).throw(RuntimeError("private details")),
            lambda: Principal("producer-01", frozenset({"household"})),
        ))
        path = ("/api/v1/domestic/household-intake/my-drafts/DEMO-H-01/"
                "surplus-offers/DEMO-OFFER-01/publication-readiness")
        response = TestClient(app).get(path)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private details", response.text)


if __name__ == "__main__":
    unittest.main()
