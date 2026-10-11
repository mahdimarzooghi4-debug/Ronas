"""Local checkpoint control: rollback, replacement, tamper and trust limits."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ronas_api.internal_authority_revision_journal_sqlite import (
    SqliteSyntheticAuthorityRevisionJournal,
)
from ronas_api.internal_authority_local_checkpoint_sqlite import (
    LocalCheckpointMismatch, SqliteLocalAuthorityCheckpoint,
)
from ronas_api.internal_authority_revision_witness import ASSIGNMENT

ACTOR="synthetic-agronomy-one"
REF="DEMO-D-1"
VER=3


class LocalAuthorityCheckpointTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db=Path(temp.name)/"journal.db"
        self.side=Path(temp.name)/"checkpoint.db"
        self.journal=SqliteSyntheticAuthorityRevisionJournal(self.db)
        self.checkpoint=SqliteLocalAuthorityCheckpoint(self.side)

    def record(self, action, value, expected):
        return self.journal.record_owned_snapshot(
            kind=ASSIGNMENT,subject=ACTOR,case_ref=REF,case_version=VER,
            snapshot=value,action_ref=action,expected_generation=expected,
        )

    def test_unpinned_and_unsealed_progress_fail_closed(self):
        with self.assertRaises(LocalCheckpointMismatch):
            self.checkpoint.assert_current(self.journal)
        first=self.checkpoint.pin_current(self.journal)
        self.assertEqual(first["event_sequence"],0)
        self.assertTrue(self.checkpoint.assert_current(self.journal)[
            "verified_against_separate_local_file"])
        self.record("DEMO-PIN-ONE",True,0)
        with self.assertRaises(LocalCheckpointMismatch):
            self.checkpoint.assert_current(self.journal)
        pinned=self.checkpoint.pin_current(self.journal)
        self.assertEqual(pinned["event_sequence"],1)
        self.assertEqual(pinned["checkpoint_ordinal"],2)
        self.assertEqual(self.checkpoint.pin_current(self.journal),pinned)
        self.assertTrue(self.checkpoint.assert_current(self.journal)[
            "verified_against_separate_local_file"])

    def test_rollback_to_older_complete_valid_db_is_detected(self):
        self.record("DEMO-FIRST",True,0)
        self.checkpoint.pin_current(self.journal)
        older=self.db.parent/"older.db"
        with sqlite3.connect(self.db) as original:
            with sqlite3.connect(older) as snapshot:
                original.backup(snapshot)
        self.record("DEMO-SECOND",False,1)
        self.checkpoint.pin_current(self.journal)
        with sqlite3.connect(older) as snapshot:
            with sqlite3.connect(self.db) as original:
                snapshot.backup(original)
        reopened=SqliteSyntheticAuthorityRevisionJournal(self.db)
        self.assertTrue(reopened.verify_integrity())
        with self.assertRaises(LocalCheckpointMismatch):
            self.checkpoint.assert_current(reopened)
        with self.assertRaises(LocalCheckpointMismatch):
            self.checkpoint.pin_current(reopened)

    def test_whole_file_replacement_even_at_same_sequence_rejected(self):
        self.checkpoint.pin_current(self.journal)
        different=self.db.parent/"different.db"
        new=SqliteSyntheticAuthorityRevisionJournal(different)
        self.assertNotEqual(
            self.checkpoint.pin_current(self.journal)["journal_id"],
            new.checkpoint_identity if hasattr(new,"checkpoint_identity") else
            self._id_for(new),
        )
        with sqlite3.connect(different) as src:
            with sqlite3.connect(self.db) as dst:
                src.backup(dst)
        restored=SqliteSyntheticAuthorityRevisionJournal(self.db)
        with self.assertRaises(LocalCheckpointMismatch):
            self.checkpoint.assert_current(restored)

    def _id_for(self,journal):
        with sqlite3.connect(journal.path) as db:
            return db.execute(
                "SELECT value FROM authority_metadata "
                "WHERE key='journal_instance_id'"
            ).fetchone()[0]

    def test_checkpoint_is_restart_safe_and_detects_unpinned_append(self):
        self.record("DEMO-FIRST",True,0)
        self.checkpoint.pin_current(self.journal)
        new_journal=SqliteSyntheticAuthorityRevisionJournal(self.db)
        new_anchor=SqliteLocalAuthorityCheckpoint(self.side)
        self.assertTrue(new_anchor.assert_current(new_journal)[
            "verified_against_separate_local_file"])
        self.record("DEMO-SECOND",False,1)
        with self.assertRaises(LocalCheckpointMismatch):
            new_anchor.assert_current(new_journal)

    def test_corrupted_checkpoint_event_is_not_accepted(self):
        self.record("DEMO-FIRST",True,0)
        self.checkpoint.pin_current(self.journal)
        with sqlite3.connect(self.side) as conn:
            conn.execute("DROP TRIGGER local_checkpoint_no_update")
            conn.execute(
                "UPDATE local_checkpoint SET event_sequence=0 WHERE ordinal=1"
            )
        with self.assertRaises(LocalCheckpointMismatch):
            self.checkpoint.assert_current(self.journal)
        with self.assertRaises(LocalCheckpointMismatch):
            self.checkpoint.pin_current(self.journal)

    def test_parallel_pin_idempotent_and_no_silent_rollback_reset(self):
        self.record("DEMO-FIRST",True,0)
        another=SqliteLocalAuthorityCheckpoint(self.side)
        with ThreadPoolExecutor(max_workers=2) as pool:
            pins=list(pool.map(lambda a:a.pin_current(self.journal),
                               [self.checkpoint,another]))
        self.assertEqual(pins[0],pins[1])
        self.assertEqual(pins[0]["checkpoint_ordinal"],1)
        self.record("DEMO-SECOND",False,1)
        self.checkpoint.pin_current(self.journal)
        with sqlite3.connect(self.side) as conn:
            count=conn.execute(
                "SELECT COUNT(*) FROM local_checkpoint"
            ).fetchone()[0]
        self.assertEqual(count,2)
        self.assertTrue(another.assert_current(self.journal)[
            "verified_against_separate_local_file"])

    def test_missing_separate_file_cannot_reconstitute_existing_trust(self):
        self.record("DEMO-FIRST",True,0)
        self.checkpoint.pin_current(self.journal)
        # New empty sidecar is not automatically trusted on a strict read.
        other=SqliteLocalAuthorityCheckpoint(
            self.db.parent/"different-checkpoint.db"
        )
        with self.assertRaises(LocalCheckpointMismatch):
            other.assert_current(self.journal)

    def test_checkpoint_same_database_and_unprotected_path_forbidden(self):
        with self.assertRaises(ValueError):
            self.checkpoint.assert_current(
                SqliteSyntheticAuthorityRevisionJournal(self.side)
            )
        with self.assertRaises(ValueError):
            SqliteLocalAuthorityCheckpoint(Path("relative-checkpoint.db"))
