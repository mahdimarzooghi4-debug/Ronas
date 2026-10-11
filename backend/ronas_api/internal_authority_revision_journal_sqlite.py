"""Durable single-host LOCAL/TEST journal for independent synthetic revisions.

Legacy reference mode stores only hashes; optional journal-owned LOCAL/TEST
mode atomically records typed DEMO candidate state and its revision.
Real science, qualifications, lawful appointments, and Production authority are
NOT established by a locally persisted counter. External updates MUST be
coupled to their producer's version transaction in any future real adapter.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat
from uuid import uuid4, UUID
from typing import Callable, Iterator

from .grant_ledger_sqlite import LedgerIntegrityError
from .internal_authority_revision_witness import (
    ASSIGNMENT, KINDS, SCIENCE, SPECIALIST, SyntheticAuthorityWitness,
)
from .internal_scientific_basis_contract import ScientificSourceCandidate
from .internal_specialist_scope_contract import (
    SyntheticSpecialistEvidenceRegistry, SpecialistScopeEvidenceCandidate,
    SpecialistScopeEvidenceEvent, _canonical as specialist_event_canonical,
)
from .scoped_drafts import _synthetic_ref, _synthetic_subject

VERSION = "ronas.domestic.local-synthetic-authority-journal.v0"
GENESIS = "0" * 64


class SyntheticAuthorityRevisionConflict(ValueError):
    """Stale expected generation, reused action, or invalid replay."""


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _sha(value: object) -> str:
    return sha256(_canonical(value).encode("ascii")).hexdigest()


def _scope(kind: str, subject: str, ref: str, version: int) -> tuple:
    if (kind not in KINDS or not _synthetic_subject(subject)
            or not _synthetic_ref(ref) or type(version) is not int
            or version < 1):
        raise ValueError("invalid synthetic authority scope")
    return kind, subject, ref, version


def snapshot_digest(kind: str, subject: str, ref: str,
                    version: int, snapshot: object) -> str:
    """Hash the actual typed synthetic snapshot relevant to ONE scope."""
    scope = _scope(kind, subject, ref, version)
    if kind == SCIENCE:
        if (type(snapshot) is not tuple or
                any(not isinstance(s, ScientificSourceCandidate)
                    for s in snapshot) or
                len({s.ref for s in snapshot}) != len(snapshot)):
            raise ValueError("invalid synthetic source snapshot")
        data = [
            (s.ref, s.version, s.content_sha256,
             s.rights_document_ref, s.rights_document_sha256,
             s.science_review_request_ref, s.science_review_material_sha256,
             s.purpose, s.status)
            for s in sorted(snapshot, key=lambda x: x.ref)
        ]
    elif kind == SPECIALIST:
        if not isinstance(snapshot, SyntheticSpecialistEvidenceRegistry):
            raise ValueError("invalid independent specialist registry")
        snapshot.project_assigned_case(
            subject=subject, case_ref=ref, case_version=version,
        )
        data = [
            specialist_event_canonical(e) for e in snapshot.events
            if e.subject == subject and e.case_ref == ref
        ]
    else:
        if type(snapshot) is not bool:
            raise ValueError("assignment authority must explicitly report bool")
        data = snapshot
    return _sha({"contract": VERSION, "scope": scope, "candidate_snapshot": data})



def _owned_json(kind: str, subject: str, ref: str, version: int,
                snapshot: object) -> str:
    """Only DEMO pointer metadata; preserve exactly one actor/case scope."""
    digest = snapshot_digest(kind, subject, ref, version, snapshot)
    if kind == SCIENCE:
        entries = [asdict(s) for s in sorted(snapshot, key=lambda s: s.ref)]
    elif kind == SPECIALIST:
        entries = [asdict(e) for e in snapshot.events
                   if e.subject == subject and e.case_ref == ref]
    else:
        entries = snapshot
    return _canonical({"contract": VERSION,
                       "kind": kind,
                       "snapshot_digest_sha256": digest,
                       "entries": entries})


def _load_owned(kind: str, subject: str, ref: str, version: int,
                raw: str) -> object:
    """Rebuild typed current LOCAL/TEST snapshot and revalidate digest."""
    try:
        data = json.loads(raw)
        if (type(data) is not dict or set(data) != {
                "contract", "kind", "snapshot_digest_sha256", "entries"
            } or data["contract"] != VERSION or data["kind"] != kind
                or _canonical(data) != raw):
            raise ValueError("noncanonical owned authority state")
        entries = data["entries"]
        if kind == SCIENCE:
            if type(entries) is not list:
                raise ValueError("invalid source entries")
            snapshot = tuple(ScientificSourceCandidate(**s) for s in entries)
        elif kind == SPECIALIST:
            if type(entries) is not list:
                raise ValueError("invalid specialist entries")
            events = []
            for entry in entries:
                if type(entry) is not dict:
                    raise ValueError("invalid specialist evidence event")
                item = dict(entry)
                candidate = item.get("candidate")
                if candidate is not None:
                    c = dict(candidate)
                    c["declared_review_tracks"] = tuple(
                        c["declared_review_tracks"]
                    )
                    item["candidate"] = SpecialistScopeEvidenceCandidate(**c)
                events.append(SpecialistScopeEvidenceEvent(**item))
            snapshot = SyntheticSpecialistEvidenceRegistry(tuple(events))
        else:
            if type(entries) is not bool:
                raise ValueError("invalid assignment state")
            snapshot = entries
        digest = snapshot_digest(kind, subject, ref, version, snapshot)
        if digest != data["snapshot_digest_sha256"]:
            raise ValueError("owned snapshot digest mismatch")
        return snapshot
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise LedgerIntegrityError("owned authority snapshot invalid") from exc


class SqliteSyntheticAuthorityRevisionJournal:
    """Restart-safe, serializable LOCAL/TEST witness producer.

    In explicitly selected owned mode, typed DEMO candidate state and its
    append-only version event share ONE local SQLite transaction. This does
    not govern or certify any real independent external provider state.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if (not self.path.is_absolute() or self.path.is_symlink()
                or not self.path.parent.is_dir()):
            raise ValueError("absolute non-symlink local journal required")
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if self.path.is_symlink():
                raise ValueError("symlink journal forbidden") from None
        else:
            os.close(fd)
        st = self.path.stat()
        if (not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077
                or hasattr(os, "getuid") and st.st_uid != os.getuid()):
            raise ValueError("authority journal must be a private regular file")
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS authority_metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS authority_event (
                    sequence INTEGER PRIMARY KEY,
                    action_ref TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL, subject TEXT NOT NULL,
                    case_ref TEXT NOT NULL, case_version INTEGER NOT NULL,
                    generation INTEGER NOT NULL,
                    snapshot_digest TEXT NOT NULL,
                    previous_digest TEXT NOT NULL, event_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS authority_owned_scope (
                    kind TEXT NOT NULL, subject TEXT NOT NULL,
                    case_ref TEXT NOT NULL, case_version INTEGER NOT NULL,
                    PRIMARY KEY(kind,subject,case_ref,case_version)
                );
                CREATE TABLE IF NOT EXISTS authority_owned_state (
                    kind TEXT NOT NULL, subject TEXT NOT NULL,
                    case_ref TEXT NOT NULL, case_version INTEGER NOT NULL,
                    generation INTEGER NOT NULL,
                    snapshot_digest TEXT NOT NULL, snapshot_json TEXT NOT NULL,
                    PRIMARY KEY(kind,subject,case_ref,case_version),
                    FOREIGN KEY(kind,subject,case_ref,case_version)
                      REFERENCES authority_owned_scope(kind,subject,case_ref,case_version)
                );
                CREATE TRIGGER IF NOT EXISTS authority_owned_scope_no_update
                BEFORE UPDATE ON authority_owned_scope BEGIN
                    SELECT RAISE(ABORT,'immutable owned scope');
                END;
                CREATE TRIGGER IF NOT EXISTS authority_owned_scope_no_delete
                BEFORE DELETE ON authority_owned_scope BEGIN
                    SELECT RAISE(ABORT,'immutable owned scope');
                END;
                CREATE TRIGGER IF NOT EXISTS authority_owned_state_no_delete
                BEFORE DELETE ON authority_owned_state BEGIN
                    SELECT RAISE(ABORT,'owned authority state cannot be deleted');
                END;
                CREATE TRIGGER IF NOT EXISTS authority_owned_state_version_cas
                BEFORE UPDATE ON authority_owned_state
                WHEN NEW.generation != OLD.generation+1 BEGIN
                    SELECT RAISE(ABORT,'owned authority generation must increase by one');
                END;
                CREATE TRIGGER IF NOT EXISTS authority_event_no_update
                BEFORE UPDATE ON authority_event BEGIN
                    SELECT RAISE(ABORT,'immutable authority event');
                END;
                CREATE TRIGGER IF NOT EXISTS authority_event_no_delete
                BEFORE DELETE ON authority_event BEGIN
                    SELECT RAISE(ABORT,'immutable authority event');
                END;
            """)
            db.execute(
                "INSERT OR IGNORE INTO authority_metadata(key,value) "
                "VALUES('head_digest',?)", (GENESIS,),
            )
            db.execute(
                "INSERT OR IGNORE INTO authority_metadata(key,value) "
                "VALUES('journal_instance_id',?)", (uuid4().hex,),
            )
        with self._transaction() as db:
            self._verify(db)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=15000")
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _verify(self, db: sqlite3.Connection) -> dict[tuple, tuple[int, str]]:
        triggers = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='authority_event'"
        )}
        if triggers != {"authority_event_no_update", "authority_event_no_delete"}:
            raise LedgerIntegrityError("authority event immutability untrusted")
        metadata = dict(db.execute(
            "SELECT key,value FROM authority_metadata"
        ))
        if set(metadata) != {"head_digest","journal_instance_id"}:
            raise LedgerIntegrityError("authority journal metadata malformed")
        try:
            instance_id = metadata["journal_instance_id"]
            if (type(instance_id) is not str or len(instance_id) != 32
                    or UUID(hex=instance_id).hex != instance_id):
                raise ValueError("invalid journal instance ID")
        except (ValueError, TypeError, AttributeError) as exc:
            raise LedgerIntegrityError("authority journal identity invalid") from exc
        previous = GENESIS
        state: dict[tuple, tuple[int, str]] = {}
        actions = set()
        for expected, row in enumerate(db.execute(
                "SELECT sequence,action_ref,kind,subject,case_ref,"
                "case_version,generation,snapshot_digest,previous_digest,"
                "event_digest FROM authority_event ORDER BY sequence"
        ), 1):
            (sequence, action, kind, subject, ref, version, generation,
             digest, prev, event_hash) = row
            try:
                scope = _scope(kind, subject, ref, version)
            except ValueError as exc:
                raise LedgerIntegrityError("invalid event scope") from exc
            last = state.get(scope, (0, None))[0]
            fields = [sequence, action, kind, subject, ref, version,
                      generation, digest, prev]
            if (type(sequence) is not int or sequence != expected
                    or not _synthetic_ref(action) or action in actions
                    or type(generation) is not int or generation != last + 1
                    or not isinstance(digest, str) or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)
                    or prev != previous or event_hash != _sha(fields)):
                raise LedgerIntegrityError("authority event chain corrupt")
            state[scope] = (generation, digest)
            actions.add(action)
            previous = event_hash
        if metadata["head_digest"] != previous:
            raise LedgerIntegrityError("authority journal head mismatch")

        owned_trigger_names = {
            r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name IN ('authority_owned_scope','authority_owned_state')"
            )
        }
        if owned_trigger_names != {
            "authority_owned_scope_no_update", "authority_owned_scope_no_delete",
            "authority_owned_state_no_delete", "authority_owned_state_version_cas"
        }:
            raise LedgerIntegrityError("owned authority mutation protection missing")
        owned_keys = {
            tuple(r) for r in db.execute(
                "SELECT kind,subject,case_ref,case_version "
                "FROM authority_owned_scope"
            )
        }
        owned_current = {}
        for row in db.execute(
            "SELECT kind,subject,case_ref,case_version,generation,"
            "snapshot_digest,snapshot_json FROM authority_owned_state"
        ):
            kind, subject, ref, version, generation, digest, raw = row
            try:
                scope = _scope(kind, subject, ref, version)
            except ValueError as exc:
                raise LedgerIntegrityError("invalid owned scope") from exc
            if scope in owned_current or state.get(scope) != (
                generation, digest
            ):
                raise LedgerIntegrityError("owned state/event version drift")
            snapshot = _load_owned(kind, subject, ref, version, raw)
            if snapshot_digest(kind, subject, ref, version, snapshot) != digest:
                raise LedgerIntegrityError("owned state data/event mismatch")
            owned_current[scope] = (generation, digest)
        if owned_keys != set(owned_current):
            raise LedgerIntegrityError("missing or orphaned owned authority state")
        return state

    def record_snapshot(
        self, *, kind: str, subject: str, case_ref: str, case_version: int,
        snapshot: object, action_ref: str, expected_generation: int,
    ) -> SyntheticAuthorityWitness:
        scope = _scope(kind, subject, case_ref, case_version)
        if (not _synthetic_ref(action_ref)
                or type(expected_generation) is not int
                or not 0 <= expected_generation < 2**63 - 1):
            raise ValueError("invalid action/expected generation")
        digest = snapshot_digest(kind, subject, case_ref, case_version, snapshot)
        with self._transaction() as db:
            states = self._verify(db)
            if db.execute(
                "SELECT 1 FROM authority_owned_scope WHERE kind=? AND "
                "subject=? AND case_ref=? AND case_version=?", scope
            ).fetchone() is not None:
                raise SyntheticAuthorityRevisionConflict(
                    "hash-only writer cannot bypass owned data/version transaction"
                )
            current = states.get(scope, (0, None))[0]
            replay = db.execute(
                "SELECT kind,subject,case_ref,case_version,generation,"
                "snapshot_digest FROM authority_event WHERE action_ref=?",
                (action_ref,),
            ).fetchone()
            if replay is not None:
                if (replay != (*scope, expected_generation + 1, digest)
                        or current != replay[4]):
                    raise SyntheticAuthorityRevisionConflict(
                        "replayed action conflicts with latest authority state"
                    )
                return SyntheticAuthorityWitness(
                    kind, subject, case_ref, case_version, replay[4],
                )
            if current != expected_generation:
                raise SyntheticAuthorityRevisionConflict(
                    "stale or reset authority generation"
                )
            seq = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM authority_event"
            ).fetchone()[0]
            prev = db.execute(
                "SELECT value FROM authority_metadata WHERE key='head_digest'"
            ).fetchone()[0]
            fields = [seq, action_ref, *scope, current + 1, digest, prev]
            event_digest = _sha(fields)
            db.execute(
                "INSERT INTO authority_event(sequence,action_ref,kind,subject,"
                "case_ref,case_version,generation,snapshot_digest,"
                "previous_digest,event_digest) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (*fields, event_digest),
            )
            db.execute(
                "UPDATE authority_metadata SET value=? WHERE key='head_digest'",
                (event_digest,),
            )
            self._verify(db)
            return SyntheticAuthorityWitness(
                kind, subject, case_ref, case_version, current + 1,
            )


    def record_owned_snapshot(
        self, *, kind: str, subject: str, case_ref: str, case_version: int,
        snapshot: object, action_ref: str, expected_generation: int,
    ) -> SyntheticAuthorityWitness:
        """Atomic typed DEMO data + immutable event + source revision.

        Only an initially empty scope may opt into journal-owned state.
        Existing hash-only scopes cannot silently be upgraded; migration of
        authentic source providers requires an explicitly reviewed contract.
        """
        scope = _scope(kind, subject, case_ref, case_version)
        if (not _synthetic_ref(action_ref)
                or type(expected_generation) is not int
                or not 0 <= expected_generation < 2**63 - 1):
            raise ValueError("invalid action or revision")
        raw = _owned_json(kind, subject, case_ref, case_version, snapshot)
        digest = snapshot_digest(kind, subject, case_ref, case_version, snapshot)
        with self._transaction() as db:
            states = self._verify(db)
            current = states.get(scope, (0, None))[0]
            owned = db.execute(
                "SELECT generation,snapshot_digest,snapshot_json "
                "FROM authority_owned_state WHERE kind=? AND subject=? "
                "AND case_ref=? AND case_version=?", scope,
            ).fetchone()
            replay = db.execute(
                "SELECT kind,subject,case_ref,case_version,generation,"
                "snapshot_digest FROM authority_event WHERE action_ref=?",
                (action_ref,),
            ).fetchone()
            if replay is not None:
                if (owned is None or current != replay[4]
                        or replay != (*scope, expected_generation+1, digest)
                        or owned != (current,digest,raw)):
                    raise SyntheticAuthorityRevisionConflict(
                        "conflicting or stale owned action replay"
                    )
                return SyntheticAuthorityWitness(*scope, current)
            if current != expected_generation:
                raise SyntheticAuthorityRevisionConflict(
                    "stale owned candidate revision"
                )
            if current and owned is None:
                raise LedgerIntegrityError(
                    "cannot adopt legacy hash-only scope without migration"
                )
            seq = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM authority_event"
            ).fetchone()[0]
            previous = db.execute(
                "SELECT value FROM authority_metadata WHERE key='head_digest'"
            ).fetchone()[0]
            fields = [seq,action_ref,*scope,current+1,digest,previous]
            event_digest = _sha(fields)
            db.execute(
                "INSERT INTO authority_event(sequence,action_ref,kind,subject,"
                "case_ref,case_version,generation,snapshot_digest,"
                "previous_digest,event_digest) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (*fields,event_digest),
            )
            if owned is None:
                db.execute(
                    "INSERT INTO authority_owned_scope(kind,subject,case_ref,"
                    "case_version) VALUES(?,?,?,?)",scope,
                )
                db.execute(
                    "INSERT INTO authority_owned_state(kind,subject,case_ref,"
                    "case_version,generation,snapshot_digest,snapshot_json)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (*scope,1,digest,raw),
                )
            else:
                db.execute(
                    "UPDATE authority_owned_state SET generation=?,"
                    "snapshot_digest=?,snapshot_json=? "
                    "WHERE kind=? AND subject=? AND case_ref=? AND case_version=?",
                    (current+1,digest,raw,*scope),
                )
            db.execute(
                "UPDATE authority_metadata SET value=? WHERE key='head_digest'",
                (event_digest,),
            )
            self._verify(db)
            return SyntheticAuthorityWitness(*scope,current+1)

    def read_owned_snapshot(
        self, *, kind: str, subject: str, case_ref: str, case_version: int,
    ) -> tuple[object, SyntheticAuthorityWitness]:
        """Return typed state and its generation from ONE verified SQL read."""
        scope = _scope(kind,subject,case_ref,case_version)
        with self._transaction() as db:
            self._verify(db)
            row = db.execute(
                "SELECT generation,snapshot_json FROM authority_owned_state "
                "WHERE kind=? AND subject=? AND case_ref=? AND case_version=?",
                scope,
            ).fetchone()
            if row is None:
                raise LedgerIntegrityError("no owned state for requested case")
            snapshot = _load_owned(kind,subject,case_ref,case_version,row[1])
            return snapshot, SyntheticAuthorityWitness(*scope,row[0])

    def owned_callback(self, kind: str) -> Callable[
        [str,str,int], SyntheticAuthorityWitness,
    ]:
        """Explicit LOCAL/TEST adapter; default app mounts nothing."""
        if kind not in KINDS:
            raise ValueError("untrusted owned domain")
        def read(subject: str, ref: str, version: int):
            return self.read_owned_snapshot(
                kind=kind,subject=subject,case_ref=ref,case_version=version,
            )[1]
        return read

    def witness_for_snapshot(
        self, *, kind: str, subject: str, case_ref: str,
        case_version: int, snapshot: object,
    ) -> SyntheticAuthorityWitness:
        scope = _scope(kind, subject, case_ref, case_version)
        current = snapshot_digest(kind, subject, case_ref, case_version, snapshot)
        with self._transaction() as db:
            latest = self._verify(db).get(scope)
            if latest is None or latest[1] != current:
                raise LedgerIntegrityError(
                    "current candidate snapshot not registered at latest revision"
                )
            return SyntheticAuthorityWitness(
                kind, subject, case_ref, case_version, latest[0],
            )

    def callback(self, kind: str, snapshot_reader: Callable[
        [str, str, int], object,
    ]) -> Callable[[str, str, int], SyntheticAuthorityWitness]:
        if kind not in KINDS or not callable(snapshot_reader):
            raise ValueError("source-owned snapshot reader required")

        def read(subject: str, ref: str, version: int):
            return self.witness_for_snapshot(
                kind=kind, subject=subject, case_ref=ref,
                case_version=version,
                snapshot=snapshot_reader(subject, ref, version),
            )
        return read

    def verify_integrity(self) -> bool:
        try:
            with self._transaction() as db:
                self._verify(db)
            return True
        except (LedgerIntegrityError, sqlite3.DatabaseError, ValueError, TypeError):
            return False
