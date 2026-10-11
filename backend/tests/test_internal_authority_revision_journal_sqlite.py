"""Durable synthetic authority generation journal / non-Production tests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from ronas_api.grant_ledger_sqlite import LedgerIntegrityError
from ronas_api.internal_authority_revision_witness import (
    ASSIGNMENT, SCIENCE, SPECIALIST,
    versioned_context_fingerprint,
)
from ronas_api.internal_authority_revision_journal_sqlite import (
    SqliteSyntheticAuthorityRevisionJournal,
    SyntheticAuthorityRevisionConflict,
)
from ronas_api.internal_scientific_basis_contract import ScientificSourceCandidate
from ronas_api.internal_specialist_scope_contract import (
    RECORDED, SpecialistScopeEvidenceCandidate, SpecialistScopeEvidenceEvent,
    SyntheticSpecialistEvidenceRegistry,
)

ACTOR, REF, VER = "synthetic-agronomy-one", "DEMO-D-1", 3


def science(version=1, digest="a"*64):
    return (ScientificSourceCandidate(
        ref="DEMO-SOURCE-1", version=version, content_sha256=digest,
        rights_document_ref="DEMO-RIGHTS-1", rights_document_sha256="b"*64,
        science_review_request_ref="DEMO-REVIEW-1",
        science_review_material_sha256="c"*64,
    ),)


def specialists():
    item=SpecialistScopeEvidenceCandidate(
        subject=ACTOR, case_ref=REF, case_version=VER,
        evidence_revision=1, declared_review_tracks=(
            "HOUSEHOLD_INPUT_ADEQUACY",
        ),
        qualification_evidence_ref="DEMO-QUAL-1",
        qualification_evidence_sha256="d"*64,
        appointment_evidence_ref="DEMO-APPOINT-1",
        appointment_evidence_sha256="e"*64,
        conflict_disclosure_ref="DEMO-CONFLICT-1",
        conflict_disclosure_sha256="f"*64,
    )
    event=SpecialistScopeEvidenceEvent(
        action_ref="DEMO-SPECIALIST-1", subject=ACTOR, case_ref=REF,
        case_version=VER, evidence_revision=1, operation=RECORDED,
        candidate=item,
    )
    return SyntheticSpecialistEvidenceRegistry((event,))


class AuthorityJournalTests(unittest.TestCase):
    def setUp(self):
        d=tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.file=Path(d.name)/"scoped.db"
        self.store=SqliteSyntheticAuthorityRevisionJournal(self.file)

    def record(self, kind, snapshot, action, expected=0, store=None,
               subject=ACTOR, case=REF, version=VER):
        return (store or self.store).record_snapshot(
            kind=kind, subject=subject, case_ref=case,
            case_version=version, snapshot=snapshot,
            action_ref=action, expected_generation=expected,
        )

    def read(self, kind, snapshot, store=None):
        return (store or self.store).witness_for_snapshot(
            kind=kind, subject=ACTOR, case_ref=REF, case_version=VER,
            snapshot=snapshot,
        )

    def test_restart_safe_and_versioned_aba(self):
        a=science()
        b=science(2,"9"*64)
        first=self.record(SCIENCE,a,"DEMO-SCI-1")
        reopened=SqliteSyntheticAuthorityRevisionJournal(self.file)
        self.assertEqual(self.read(SCIENCE,a,reopened).generation,1)
        self.record(SCIENCE,b,"DEMO-SCI-2",1,store=reopened)
        end=self.record(SCIENCE,a,"DEMO-SCI-3",2)
        self.assertEqual(end.generation,3)
        self.assertEqual(self.read(SCIENCE,a,reopened).generation,3)
        self.assertNotEqual(
            versioned_context_fingerprint(
                context_fingerprint="1"*64,
                vector=(first, self.record(SPECIALIST,specialists(),"DEMO-SP-1"),
                        self.record(ASSIGNMENT,True,"DEMO-AS-1")),
                subject=ACTOR,case_ref=REF,case_version=VER,
            ),
            versioned_context_fingerprint(
                context_fingerprint="1"*64,
                vector=(end,self.read(SPECIALIST,specialists()),
                        self.read(ASSIGNMENT,True)),
                subject=ACTOR,case_ref=REF,case_version=VER,
            ),
        )
        self.assertTrue(reopened.verify_integrity())

    def test_missing_or_stale_snapshot_fails_closed(self):
        with self.assertRaises(LedgerIntegrityError):
            self.read(SCIENCE,science())
        self.record(SCIENCE,science(),"DEMO-SCI-1")
        with self.assertRaises(LedgerIntegrityError):
            self.read(SCIENCE,science(2,"9"*64))
        with self.assertRaises(LedgerIntegrityError):
            self.read(ASSIGNMENT,True)
        self.assertEqual(self.read(SCIENCE,science()).generation,1)

    def test_duplicate_action_idempotent_but_stale_replay_rejected(self):
        a=science()
        first=self.record(SCIENCE,a,"DEMO-SCI-1")
        self.assertEqual(first,self.record(SCIENCE,a,"DEMO-SCI-1"))
        with self.assertRaises(SyntheticAuthorityRevisionConflict):
            self.record(SCIENCE,science(2),"DEMO-SCI-1")
        self.record(SCIENCE,science(2),"DEMO-SCI-2",1)
        with self.assertRaises(SyntheticAuthorityRevisionConflict):
            self.record(SCIENCE,a,"DEMO-SCI-1")
        self.assertEqual(self.read(SCIENCE,science(2)).generation,2)

    def test_revision_reset_or_skipped_revision_fails_closed(self):
        self.record(ASSIGNMENT,True,"DEMO-AS-1")
        for expected in (0,3,True,-1):
            with self.subTest(expected=expected):
                with self.assertRaises((SyntheticAuthorityRevisionConflict,ValueError)):
                    self.record(ASSIGNMENT,False,"DEMO-AS-2",expected)
        self.assertEqual(self.read(ASSIGNMENT,True).generation,1)

    def test_multi_connection_concurrent_writers_cas_single_winner(self):
        other=SqliteSyntheticAuthorityRevisionJournal(self.file)
        self.record(ASSIGNMENT,True,"DEMO-AS-1")
        def update(args):
            store,action=args
            try:
                return self.record(ASSIGNMENT,False,action,1,store=store)
            except SyntheticAuthorityRevisionConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(update,[
                (self.store,"DEMO-AS-2"),(other,"DEMO-AS-3"),
            ]))
        self.assertEqual(sum(x is not None for x in result),1)
        self.assertEqual(self.read(ASSIGNMENT,False).generation,2)
        self.assertTrue(other.verify_integrity())

    def test_independent_subject_and_case_scope_separation(self):
        self.record(ASSIGNMENT,True,"DEMO-AS-1")
        self.record(ASSIGNMENT,False,"DEMO-AS-OTHER",
                    subject="synthetic-other",case="DEMO-D-2")
        self.assertEqual(self.read(ASSIGNMENT,True).generation,1)
        self.assertEqual(self.store.witness_for_snapshot(
            kind=ASSIGNMENT,subject="synthetic-other",case_ref="DEMO-D-2",
            case_version=VER,snapshot=False,
        ).generation,1)

    def test_scoped_specialist_evidence_snapshot_and_callback(self):
        state={"scope":specialists()}
        self.record(SPECIALIST,state["scope"],"DEMO-SP-RECORD")
        reader=self.store.callback(
            SPECIALIST,lambda actor,ref,ver:state["scope"])
        self.assertEqual(reader(ACTOR,REF,VER).generation,1)
        state["scope"]=SyntheticSpecialistEvidenceRegistry()
        with self.assertRaises(LedgerIntegrityError):
            reader(ACTOR,REF,VER)
        with self.assertRaises(ValueError):
            self.store.callback(ASSIGNMENT,None)

    def test_reject_manual_update_delete_and_detect_tampered_history(self):
        self.record(SCIENCE,science(),"DEMO-SCI-1")
        with sqlite3.connect(self.file) as db:
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("DELETE FROM authority_event")
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute(
                    "UPDATE authority_event SET generation=0 WHERE sequence=1"
                )
        with sqlite3.connect(self.file) as db:
            db.execute("DROP TRIGGER authority_event_no_update")
            db.execute(
                "UPDATE authority_event SET generation=99 WHERE sequence=1"
            )
        self.assertFalse(self.store.verify_integrity())
        with self.assertRaises(LedgerIntegrityError):
            self.read(SCIENCE,science())

    def test_private_file_and_snapshot_kind_are_required(self):
        self.assertEqual(self.file.stat().st_mode & 0o077,0)
        for kind,snapshot in ((SCIENCE,True),(SPECIALIST,tuple()),
                              (ASSIGNMENT,1)):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    self.record(kind,snapshot,"DEMO-BAD")
        with self.assertRaises(ValueError):
            SqliteSyntheticAuthorityRevisionJournal(Path("relative.db"))
