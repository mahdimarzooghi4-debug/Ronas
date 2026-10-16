"""PostgreSQL integration coverage for encrypted Export research notes."""
import os
import secrets
import unittest

import psycopg

from ronas_api.auth import Principal
from ronas_api.postgres_export_findings import (
    ExportFindingStorageError, PostgresExportResearchFindingLedger,
)
from ronas_api.export_research_findings import ExportResearchFindingConflict

DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
class PostgresExportFindingLedgerTests(unittest.TestCase):
    def setUp(self):
        self.ref = "DEMO-E-" + secrets.token_hex(8).upper()
        self.principal = Principal("synthetic-export-operator", frozenset({"export_ops"}))
        self.state = {"case_version": 2, "question_revision": 1,
                      "evidence": [
                          {"evidence_revision": 1, "evidence_ref": "DEMO-EVIDENCE-1",
                           "source_ref": "DEMO-SOURCE-1", "connector_ref": "DEMO-CONNECTOR-1",
                           "source_snapshot_digest": "a" * 64},
                          {"evidence_revision": 2, "evidence_ref": "DEMO-EVIDENCE-2",
                           "source_ref": "DEMO-SOURCE-1", "connector_ref": "DEMO-CONNECTOR-1",
                           "source_snapshot_digest": "b" * 64},
                      ]}
        self.ledger = PostgresExportResearchFindingLedger(
            DSN, self.workspace, secrets.token_bytes(32),
        )

    def workspace(self, ref, principal):
        if ref != self.ref or principal != self.principal:
            return None
        return {"case_version": self.state["case_version"],
                "local_test_draft_question": {"question_revision": self.state["question_revision"]},
                "local_test_evidence_references": list(self.state["evidence"])}

    def record(self, action, expected=0):
        return self.ledger.record_export_research_finding(
            self.ref, self.principal, expected_case_version=2,
            expected_question_revision=1, expected_finding_revision=expected,
            evidence_revision=1, action_id=action, evidence_ref="DEMO-EVIDENCE-1",
            note="DEMO: sample market signal",
        )

    def test_encrypted_append_only_history_and_replay(self):
        first = self.record("PG-EXPORT-FINDING-1")
        self.assertEqual(first["revision"], 1)
        self.assertEqual(self.record("PG-EXPORT-FINDING-1"), first)
        with psycopg.connect(DSN) as db:
            row = db.execute("SELECT note_ciphertext FROM ronas_export_research_finding WHERE ref=%s", (self.ref,)).fetchone()
            self.assertNotIn(b"sample market signal", bytes(row[0]))
            with self.assertRaises(psycopg.errors.RaiseException):
                with db.transaction():
                    db.execute("UPDATE ronas_export_research_finding SET revision=7 WHERE ref=%s", (self.ref,))
        self.assertEqual(self.ledger.read_history(self.ref, self.principal), [first])
        self.assertTrue(first["draft_only"])
        self.assertFalse(first["report_approved"])
        self.assertEqual(first["evidence_binding"], "HISTORICAL")

    def test_stale_case_question_evidence_and_wrong_grant_fail_closed(self):
        with self.assertRaises(ExportResearchFindingConflict):
            self.ledger.record_export_research_finding(
                self.ref, self.principal, expected_case_version=1,
                expected_question_revision=1, expected_finding_revision=0,
                evidence_revision=1, action_id="PG-EXPORT-STALE",
                evidence_ref="DEMO-EVIDENCE-1", note="DEMO: sample market signal")
        self.assertIsNone(self.ledger.read_history(self.ref, Principal("other", frozenset({"export_ops"}))))
        self.state["question_revision"] = 2
        with self.assertRaises(ExportResearchFindingConflict):
            self.record("PG-EXPORT-OLD-QUESTION")

    def test_database_row_tampering_is_detected(self):
        self.record("PG-EXPORT-FINDING-TAMPER")
        with psycopg.connect(DSN) as db:
            db.execute("ALTER TABLE ronas_export_research_finding DISABLE TRIGGER ronas_export_finding_no_update_delete")
            db.execute("UPDATE ronas_export_research_finding SET note_digest=%s WHERE ref=%s",
                       ("b" * 64, self.ref))
            db.execute("ALTER TABLE ronas_export_research_finding ENABLE TRIGGER ronas_export_finding_no_update_delete")
        with self.assertRaises(ExportFindingStorageError):
            self.ledger.read_history(self.ref, self.principal)
