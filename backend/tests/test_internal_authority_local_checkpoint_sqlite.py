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


    def test_strict_recovery_inspection_matches_without_any_mutation(self):
        from ronas_api.internal_authority_recovery_inspection import (
            MATCHED, inspect_local_recovery,
        )
        self.record("DEMO-RECOVERY-A",True,0)
        pinned=self.checkpoint.pin_current(self.journal)
        before=self._snapshot_counts()
        result=inspect_local_recovery(self.db,self.side)
        self.assertEqual(result.state,MATCHED)
        self.assertTrue(result.local_checkpoint_matches)
        self.assertFalse(result.independent_external_attestation)
        self.assertEqual(self._snapshot_counts(),before)
        self.assertEqual(self.checkpoint.assert_current(self.journal)[
            "checkpoint_ordinal"],pinned["checkpoint_ordinal"])

    def _snapshot_counts(self):
        with sqlite3.connect(self.db) as db:
            events=db.execute("SELECT COUNT(*) FROM authority_event").fetchone()[0]
        with sqlite3.connect(self.side) as db:
            pins=db.execute("SELECT COUNT(*) FROM local_checkpoint").fetchone()[0]
        return events,pins

    def test_missing_checkpoint_file_fails_without_recreation_or_repin(self):
        from ronas_api.internal_authority_recovery_inspection import (
            MISSING_CHECKPOINT,inspect_local_recovery,
        )
        self.record("DEMO-RECOVERY-A",True,0)
        self.checkpoint.pin_current(self.journal)
        self.side.unlink()
        result=inspect_local_recovery(self.db,self.side)
        self.assertEqual(result.state,MISSING_CHECKPOINT)
        self.assertFalse(result.local_checkpoint_matches)
        self.assertFalse(self.side.exists())
        with self.assertRaises(LocalCheckpointMismatch):
            SqliteLocalAuthorityCheckpoint.open_existing(self.side)
        self.assertFalse(self.side.exists())

    def test_missing_journal_and_both_files_fail_without_recreation(self):
        from ronas_api.internal_authority_recovery_inspection import (
            MISSING_JOURNAL,MISSING_BOTH,inspect_local_recovery,
        )
        self.checkpoint.pin_current(self.journal)
        self.db.unlink()
        self.assertEqual(inspect_local_recovery(self.db,self.side).state,
                         MISSING_JOURNAL)
        with self.assertRaises(Exception):
            SqliteSyntheticAuthorityRevisionJournal.open_existing(self.db)
        self.assertFalse(self.db.exists())
        self.side.unlink()
        self.assertEqual(inspect_local_recovery(self.db,self.side).state,
                         MISSING_BOTH)
        self.assertFalse(self.db.exists())
        self.assertFalse(self.side.exists())

    def test_partial_checkpoint_recovery_reports_journal_ahead_unpinned(self):
        from ronas_api.internal_authority_recovery_inspection import (
            AHEAD,inspect_local_recovery,
        )
        self.record("DEMO-RECOVERY-A",True,0)
        self.checkpoint.pin_current(self.journal)
        old_side=self.side.parent/"oldside.db"
        with sqlite3.connect(self.side) as src:
            with sqlite3.connect(old_side) as dst:
                src.backup(dst)
        self.record("DEMO-RECOVERY-B",False,1)
        self.checkpoint.pin_current(self.journal)
        with sqlite3.connect(old_side) as src:
            with sqlite3.connect(self.side) as dst:
                src.backup(dst)
        self.assertEqual(inspect_local_recovery(self.db,self.side).state,AHEAD)
        with self.assertRaises(LocalCheckpointMismatch):
            self.checkpoint.assert_current(self.journal)

    def test_partial_journal_recovery_reports_behind_and_denies_repin(self):
        from ronas_api.internal_authority_recovery_inspection import (
            BEHIND,inspect_local_recovery,
        )
        self.record("DEMO-RECOVERY-A",True,0)
        self.checkpoint.pin_current(self.journal)
        old_main=self.db.parent/"oldmain.db"
        with sqlite3.connect(self.db) as src:
            with sqlite3.connect(old_main) as dst:
                src.backup(dst)
        self.record("DEMO-RECOVERY-B",False,1)
        self.checkpoint.pin_current(self.journal)
        with sqlite3.connect(old_main) as src:
            with sqlite3.connect(self.db) as dst:
                src.backup(dst)
        self.assertEqual(inspect_local_recovery(self.db,self.side).state,BEHIND)
        with self.assertRaises(LocalCheckpointMismatch):
            self.checkpoint.pin_current(self.journal)

    def test_replaced_and_unpinned_journal_are_not_false_matches(self):
        from ronas_api.internal_authority_recovery_inspection import (
            REPLACED,NO_CHECKPOINT,inspect_local_recovery,
        )
        self.assertEqual(inspect_local_recovery(self.db,self.side).state,
                         NO_CHECKPOINT)
        self.checkpoint.pin_current(self.journal)
        replacement=self.db.parent/"replacement.db"
        SqliteSyntheticAuthorityRevisionJournal(replacement)
        with sqlite3.connect(replacement) as src:
            with sqlite3.connect(self.db) as dst:
                src.backup(dst)
        self.assertEqual(inspect_local_recovery(self.db,self.side).state,
                         REPLACED)

    def test_corrupt_journal_or_checkpoint_detected_not_repaired(self):
        from ronas_api.internal_authority_recovery_inspection import (
            JOURNAL_UNTRUSTED,CHECKPOINT_UNTRUSTED,inspect_local_recovery,
        )
        self.record("DEMO-RECOVERY-A",True,0)
        self.checkpoint.pin_current(self.journal)
        with sqlite3.connect(self.side) as db:
            db.execute("DROP TRIGGER local_checkpoint_no_delete")
        self.assertEqual(inspect_local_recovery(self.db,self.side).state,
                         CHECKPOINT_UNTRUSTED)
        with self.assertRaises(LocalCheckpointMismatch):
            SqliteLocalAuthorityCheckpoint.open_existing(self.side)
        with sqlite3.connect(self.side) as db:
            db.execute("""CREATE TRIGGER local_checkpoint_no_delete
                BEFORE DELETE ON local_checkpoint
                BEGIN SELECT RAISE(ABORT,'immutable checkpoint'); END""")
        with sqlite3.connect(self.db) as db:
            db.execute("DROP TRIGGER authority_event_no_update")
        self.assertEqual(inspect_local_recovery(self.db,self.side).state,
                         JOURNAL_UNTRUSTED)
        from ronas_api.grant_ledger_sqlite import LedgerIntegrityError
        with self.assertRaises(LedgerIntegrityError):
            SqliteSyntheticAuthorityRevisionJournal.open_existing(self.db)

    def test_strict_open_existing_refuses_empty_or_incomplete_sqlite(self):
        from ronas_api.grant_ledger_sqlite import LedgerIntegrityError
        temp=self.db.parent
        incomplete_j=temp/"partialjournal.db"
        incomplete_c=temp/"partialcheckpoint.db"
        sqlite3.connect(incomplete_j).close()
        sqlite3.connect(incomplete_c).close()
        incomplete_j.chmod(0o600)
        incomplete_c.chmod(0o600)
        with self.assertRaises((LedgerIntegrityError,sqlite3.DatabaseError)):
            SqliteSyntheticAuthorityRevisionJournal.open_existing(incomplete_j)
        with self.assertRaises((LocalCheckpointMismatch,sqlite3.DatabaseError)):
            SqliteLocalAuthorityCheckpoint.open_existing(incomplete_c)
        for f in (incomplete_j,incomplete_c):
            with sqlite3.connect(f) as db:
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0],0)

    def test_both_files_rolled_back_together_remain_unprovable(self):
        from ronas_api.internal_authority_recovery_inspection import (
            MATCHED,inspect_local_recovery,
        )
        self.record("DEMO-RECOVERY-A",True,0)
        self.checkpoint.pin_current(self.journal)
        backup_j=self.db.parent/"backupj.db"
        backup_c=self.db.parent/"backupc.db"
        for srcname,dstname in ((self.db,backup_j),(self.side,backup_c)):
            with sqlite3.connect(srcname) as src:
                with sqlite3.connect(dstname) as dst:
                    src.backup(dst)
        self.record("DEMO-RECOVERY-B",False,1)
        self.checkpoint.pin_current(self.journal)
        for srcname,dstname in ((backup_j,self.db),(backup_c,self.side)):
            with sqlite3.connect(srcname) as src:
                with sqlite3.connect(dstname) as dst:
                    src.backup(dst)
        # Explicitly proves the LIMIT: two coherent rolled-back local
        # files are indistinguishable without an external trusted witness.
        check=inspect_local_recovery(self.db,self.side)
        self.assertEqual(check.state,MATCHED)
        self.assertFalse(check.independent_external_attestation)

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
