"""PostgreSQL integration coverage for encrypted household progress journals."""
import os
import secrets
import tempfile
import unittest

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ronas_api.auth import Principal
from ronas_api.household_input_api import build_household_input_router
from ronas_api.household_input_profiles import (
    HouseholdInputField, HouseholdInputSchema, SqliteSyntheticHouseholdProfileLedger,
)
from ronas_api.postgres_household_progress_notes import PostgresHouseholdProgressNoteLedger
from ronas_api.scoped_drafts import ScopedDraft


DSN = os.environ.get("RONAS_TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "RONAS_TEST_POSTGRES_DSN is not configured")
class PostgresHouseholdProgressNoteTests(unittest.TestCase):
    def setUp(self):
        self.ref = "DEMO-PROGRESS-" + secrets.token_hex(6).upper()
        self.owner = "synthetic-progress-" + secrets.token_hex(6)
        self.principal = Principal(self.owner, frozenset({"household"}))
        self.schema = HouseholdInputSchema("RONAS-PROGRESS-TEST", 1, (
            HouseholdInputField("sample", "Sample", max_length=20),
        ))
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.case_ledger = SqliteSyntheticHouseholdProfileLedger(
            os.path.join(temp.name, "case.db"),
            (ScopedDraft(self.ref, "DOMESTIC", self.owner, 1, ()),),
            profile_schema=self.schema,
            trusted_revoke_authorizer=lambda *_: False,
            trusted_human_review_authorizer=lambda *_: False,
        )

        def authority(principal, ref, schema_ref):
            return (principal.subject == self.owner and ref == self.ref
                    and schema_ref == self.schema.schema_ref
                    and "household" in principal.roles)

        self.authority = authority
        self.ledger = PostgresHouseholdProgressNoteLedger(
            DSN, self.schema.schema_ref, self.authority,
            self.case_ledger.progress_note_context,
            secrets.token_bytes(32), secrets.token_bytes(32),
        )

    def append(self, *, action="DEMO-PROGRESS-1", expected=0,
               note="DEMO: grew a test leaf", correction=None):
        return self.ledger.append_owned_progress_note(
            self.ref, self.principal, action_id=action,
            expected_case_version=1, expected_revision=expected,
            expected_input_revision=0, corrects_revision=correction,
            reported_at="2026-10-17T10:00:00+00:00", note=note,
        )

    def test_encrypted_persistent_history_replay_and_correction(self):
        first = self.append()
        self.assertEqual(first["revision"], 1)
        self.assertTrue(self.append()["idempotent_replay"])
        second = self.append(action="DEMO-PROGRESS-2", expected=1,
                             note="DEMO: corrected test detail", correction=1)
        self.assertEqual(second["revision"], 2)
        result = self.ledger.read_owned_progress_notes(self.ref, self.principal)
        self.assertEqual([n["note"] for n in result["notes"]], [
            "DEMO: grew a test leaf", "DEMO: corrected test detail",
        ])
        self.assertTrue(result["notes"][0]["is_superseded"])
        self.assertFalse(result["real_data"])
        with psycopg.connect(DSN) as db:
            stored = db.execute("""SELECT note_ciphertext FROM ronas_domestic_progress_note
                WHERE household_ref=%s ORDER BY revision""", (self.ref,)).fetchall()
        self.assertTrue(all(b"grew a test leaf" not in bytes(row[0]) for row in stored))
        self.assertEqual(self.ledger.read_owned_progress_notes(
            self.ref, self.principal,
        )["current_revision"], 2)

    def test_owner_authority_and_compare_and_swap_fail_closed(self):
        self.assertIsNone(self.ledger.read_owned_progress_notes(
            self.ref, Principal("synthetic-other-owner", frozenset({"household"})),
        ))
        self.append()
        with self.assertRaises(ValueError):
            self.append(action="DEMO-PROGRESS-STALE")
        with self.assertRaises(ValueError):
            self.append(action="DEMO-PROGRESS-CORRECTION", expected=0,
                        correction=1)

    def test_postgres_rows_are_immutable(self):
        self.append()
        with self.assertRaises(psycopg.errors.RaiseException):
            with psycopg.connect(DSN) as db:
                db.execute("UPDATE ronas_domestic_progress_note SET revision=99 "
                           "WHERE household_ref=%s", (self.ref,))

    def test_full_length_unicode_note_fits_encrypted_storage_bound(self):
        note = "DEMO: " + "😀" * 144
        self.assertEqual(len(note), 150)
        saved = self.ledger.append_owned_progress_note(
            self.ref, self.principal, action_id="DEMO-PROGRESS-UNICODE",
            expected_case_version=1, expected_revision=0,
            expected_input_revision=0,
            reported_at="2026-10-17T10:00:00+00:00", note=note,
        )
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(self.ledger.read_owned_progress_notes(
            self.ref, self.principal,
        )["notes"][0]["note"], note)

    def test_household_api_reads_and_writes_the_injected_postgres_store(self):
        app = FastAPI()
        app.include_router(build_household_input_router(
            self.case_ledger, lambda: self.principal,
            profile_schema=self.schema,
            profile_access_authority=self.authority,
            progress_note_ledger=self.ledger,
        ))
        client = TestClient(app)
        body = {"action_id": "DEMO-PROGRESS-API", "expected_case_version": 1,
                "expected_revision": 0, "expected_input_revision": 0,
                "corrects_revision": 0,
                "reported_at": "2026-10-17T10:00:00+00:00",
                "note": "DEMO: API journal entry"}
        denied = client.post(
            f"/api/v1/domestic/household-intake/my-drafts/{self.ref}/progress-notes",
            json=body,
        )
        self.assertEqual(denied.status_code, 401)
        saved = client.post(
            f"/api/v1/domestic/household-intake/my-drafts/{self.ref}/progress-notes",
            json=body, headers={"Authorization": "Bearer test"},
        )
        self.assertEqual(saved.status_code, 201, saved.text)
        read = client.get(
            f"/api/v1/domestic/household-intake/my-drafts/{self.ref}/progress-notes",
        )
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["notes"][0]["note"], body["note"])


if __name__ == "__main__":
    unittest.main()
