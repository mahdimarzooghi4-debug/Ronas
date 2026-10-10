"""Synthetic, in-process contract tests; no real household or supplier records."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unittest
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

from ronas_core import (
    ConsentEvidence, DeclaredFact, ResearchSource, ResearchFinding,
    build_household_intake_draft, build_research_draft,
)


def consent(granted=True, purpose="CULTIVATION_CONTEXT_INTAKE"):
    return ConsentEvidence(
        subject_ref="SYNTHETIC_HOUSEHOLD",
        receipt_ref="SYNTHETIC_CONSENT_REF",
        purpose=purpose,
        explicitly_granted=granted,
        captured_at=datetime(2026, 10, 10, tzinfo=timezone.utc),
    )


def fact(name="space_description"):
    return DeclaredFact(
        field_name=name, value="SYNTHETIC_DECLARATION",
        source_ref="SYNTHETIC_SELF_REPORT",
    )


def source():
    return ResearchSource(
        reference="SYNTHETIC_PUBLIC_SOURCE",
        title="Synthetic example (not a real market source)",
        retrieved_on=date(2026, 10, 10),
        rights_caveat="UNVERIFIED: no redistribution or model-training rights assumed",
    )


def finding(ref="SYNTHETIC_PUBLIC_SOURCE"):
    return ResearchFinding(
        statement="Synthetic research note, not a market claim",
        source_ref=ref,
        limitation="No commercial conclusions may be drawn",
    )


class DomesticTests(unittest.TestCase):
    def test_consent_gated_draft_is_nonoperational(self):
        item = build_household_intake_draft(consent(), [fact()])
        self.assertEqual(item.engine, "DOMESTIC")
        self.assertEqual(item.status, "DRAFT_ONLY")
        self.assertEqual(item.consent_ref, "SYNTHETIC_CONSENT_REF")
        self.assertEqual(len(item.facts), 1)
        self.assertFalse(hasattr(item, "crop_plan_approved"))
        self.assertFalse(hasattr(item, "sale_eligible"))

    def test_refuse_declined_consent(self):
        with self.assertRaises(ValueError):
            build_household_intake_draft(consent(False), [fact()])

    def test_refuse_unrelated_consent(self):
        with self.assertRaises(ValueError):
            build_household_intake_draft(consent(purpose="TRAINING"), [fact()])

    def test_refuse_missing_consent_or_fields(self):
        for bad_consent, fields in ((None, [fact()]), (consent(), [])):
            with self.subTest(fields=fields):
                with self.assertRaises(ValueError):
                    build_household_intake_draft(bad_consent, fields)

    def test_refuse_ambiguous_duplicate_fields(self):
        with self.assertRaises(ValueError):
            build_household_intake_draft(consent(), [fact(), fact()])

    def test_refuse_blank_declaration_without_guessing(self):
        with self.assertRaises(ValueError):
            DeclaredFact(field_name="space", value=" ", source_ref="caller")

    def test_consent_provenance_requires_aware_time(self):
        with self.assertRaises(ValueError):
            ConsentEvidence("SYNTH", "RCPT", "CULTIVATION_CONTEXT_INTAKE", True,
                            datetime(2026, 10, 10))

    def test_frozen_record_and_no_write_side_effects(self):
        result = build_household_intake_draft(consent(), [fact()])
        with self.assertRaises(FrozenInstanceError):
            result.status = "APPROVED"


class ExportTests(unittest.TestCase):
    def test_research_is_citation_linked_draft_only(self):
        result = build_research_draft(
            product="SYNTHETIC_PRODUCT",
            destination="SYNTHETIC_DESTINATION",
            research_question="Synthetic trade research question",
            sources=[source()],
            findings=[finding()],
        )
        self.assertEqual(result.status, "DRAFT_ONLY")
        self.assertEqual(result.engine, "EXPORT")
        self.assertEqual(result.findings[0].source_ref, result.sources[0].reference)
        self.assertFalse(hasattr(result, "verified_buyer"))
        self.assertFalse(hasattr(result, "contract"))

    def test_refuse_missing_product_or_destination(self):
        for product, destination in (("", "X"), ("X", ""), (None, "X")):
            with self.subTest(product=product, destination=destination):
                with self.assertRaises(ValueError):
                    build_research_draft(
                        product=product, destination=destination,
                        research_question="Question", sources=[source()],
                        findings=[finding()],
                    )

    def test_refuse_missing_or_duplicate_source(self):
        for sources in ([], [source(), source()]):
            with self.assertRaises(ValueError):
                build_research_draft(
                    product="X", destination="Y", research_question="Z",
                    sources=sources, findings=[finding()],
                )

    def test_refuse_unsupported_finding(self):
        with self.assertRaises(ValueError):
            build_research_draft(
                product="X", destination="Y", research_question="Z",
                sources=[source()], findings=[finding(ref="UNLISTED")],
            )

    def test_refuse_missing_source_rights_caveat(self):
        with self.assertRaises(ValueError):
            ResearchSource("REF", "Title", date(2026, 10, 10), "")

    def test_research_source_is_not_a_license_or_market_verification(self):
        result = build_research_draft(
            product="SYNTHETIC", destination="SYNTHETIC",
            research_question="Synthetic example", sources=[source()], findings=[]
        )
        self.assertEqual(result.status, "DRAFT_ONLY")
        self.assertEqual(len(result.findings), 0)
        with self.assertRaises(FrozenInstanceError):
            result.status = "VERIFIED"


if __name__ == "__main__":
    unittest.main()
