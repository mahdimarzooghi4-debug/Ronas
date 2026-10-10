"""Append-only LOCAL/TEST Business evidence handoff, never gate approval.

Reference *metadata* only. Real files, human qualifications, source rights
and Business decisions are intentionally absent. No public mutation API.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Callable, Iterator

from .auth import Principal
from .business_gate_evidence import (
    BUSINESS_SOURCE_SHA, DOSSIERS, verify_pinned_business_sources,
)

GENESIS = "0" * 64
STAGES = ("REFERENCE_RECORDED", "HUMAN_NOTE_RECORDED")
REF_PATTERN = re.compile(r"^DEMO-[A-Z0-9][A-Z0-9-]{0,71}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class HandoffIntegrityError(RuntimeError):
    """Cannot trust the local append-only reference history."""


class HandoffConflict(ValueError):
    """Revision, action replay or workflow sequencing conflict."""


class HandoffNotAuthorized(PermissionError):
    """No actual signed role / independent reviewer authority."""


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def recognized(domain: str, evidence_id: str):
    return next((d for d in DOSSIERS if d.domain == domain
                 and any(e.evidence_id == evidence_id for e in d.evidence)), None)


def _ref(value: object) -> bool:
    return isinstance(value, str) and bool(REF_PATTERN.fullmatch(value))


def _hex(value: object) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


@dataclass(frozen=True, slots=True)
class HandoffEvent:
    sequence: int
    action_id: str
    domain: str
    evidence_id: str
    stage: str
    revision: int
    actor_digest: str
    reference_ref: str
    claimed_sha256: str
    note_ref: str | None
    previous_digest: str
    event_digest: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_digest"}

    def public_status(self) -> dict:
        return {
            "domain": self.domain, "evidence_id": self.evidence_id,
            "technical_state": self.stage, "review_revision": self.revision,
            "gate_status_at_source": "OPEN",
            "evidence_verified": False, "rights_verified": False,
            "business_approval": False, "business_source_sha": BUSINESS_SOURCE_SHA,
            "snapshot_state": "PINNED_DRAFT_SNAPSHOT_NOT_LIVE",
        }


class SqliteSyntheticGateEvidenceHandoff:
    """Explicitly injected technical adapter; no implied review authority."""

    def __init__(self, path: str | Path, *,
                 trusted_review_authorizer: Callable[[str, str, str], bool]):
        if not callable(trusted_review_authorizer):
            raise ValueError("explicit independent review authorizer required")
        self.path = Path(path)
        if (not self.path.is_absolute() or self.path.is_symlink()
                or not self.path.parent.is_dir()):
            raise ValueError("absolute private local SQLite path required")
        self._review_authorizer = trusted_review_authorizer
        verify_pinned_business_sources()
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if self.path.is_symlink():
                raise ValueError("symlink handoff ledger forbidden") from None
        else:
            os.close(fd)
        info = self.path.stat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                or hasattr(os, "getuid") and info.st_uid != os.getuid()):
            raise ValueError("handoff ledger must be owner-private")
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS handoff_event (
                    sequence INTEGER PRIMARY KEY,
                    action_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    previous_digest TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS handoff_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS handoff_no_update
                BEFORE UPDATE ON handoff_event
                BEGIN SELECT RAISE(ABORT, 'append-only handoff'); END;
                CREATE TRIGGER IF NOT EXISTS handoff_no_delete
                BEFORE DELETE ON handoff_event
                BEGIN SELECT RAISE(ABORT, 'append-only handoff'); END;
            """)
        with self._transaction() as db:
            source = db.execute(
                "SELECT value FROM handoff_meta WHERE key='source_sha'"
            ).fetchone()
            if source is None:
                db.execute(
                    "INSERT INTO handoff_meta VALUES ('source_sha', ?)",
                    (BUSINESS_SOURCE_SHA,),
                )
                db.execute("INSERT INTO handoff_meta VALUES ('head', ?)", (GENESIS,))
            self._verify(db)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
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

    def _verify(self, db: sqlite3.Connection) -> list[HandoffEvent]:
        meta = dict(db.execute("SELECT key, value FROM handoff_meta"))
        if set(meta) != {"source_sha", "head"} or meta["source_sha"] != BUSINESS_SOURCE_SHA:
            raise HandoffIntegrityError("invalid source metadata")
        prev = GENESIS
        last: dict[tuple[str, str], HandoffEvent] = {}
        actions: set[str] = set()
        events: list[HandoffEvent] = []
        for seq, action, payload, stored_digest, previous in db.execute(
            "SELECT sequence, action_id, payload, digest, previous_digest "
            "FROM handoff_event ORDER BY sequence"
        ):
            try:
                data = json.loads(payload)
                event = HandoffEvent(**data, event_digest=stored_digest)
            except (TypeError, ValueError, KeyError) as exc:
                raise HandoffIntegrityError("invalid history payload") from exc
            dossier = recognized(event.domain, event.evidence_id)
            key = (event.domain, event.evidence_id)
            former = last.get(key)
            if (type(seq) is not int or seq != len(events) + 1
                    or previous != prev or event.previous_digest != prev
                    or event.sequence != seq or event.action_id != action
                    or not _ref(action) or action in actions
                    or event.stage not in STAGES or dossier is None
                    or not _hex(event.actor_digest)
                    or not _ref(event.reference_ref) or not _hex(event.claimed_sha256)
                    or (event.note_ref is not None and not _ref(event.note_ref))
                    or event.revision != (1 if former is None else former.revision + 1)
                    or (former is None and
                        (event.stage != STAGES[0] or event.note_ref is not None))
                    or (former is not None and (
                        former.stage != STAGES[0] or event.stage != STAGES[1]
                        or event.reference_ref != former.reference_ref
                        or event.claimed_sha256 != former.claimed_sha256
                        or event.note_ref is None
                        or event.actor_digest == former.actor_digest))
                    or digest(canonical(event.payload())) != stored_digest
                    or canonical(event.payload()) != payload):
                raise HandoffIntegrityError("handoff/audit lineage mismatch")
            events.append(event)
            actions.add(action)
            last[key] = event
            prev = stored_digest
        if meta["head"] != prev:
            raise HandoffIntegrityError("handoff chain head mismatch")
        return events

    @staticmethod
    def _actor(principal: Principal, domain: str) -> str:
        dossier = next((d for d in DOSSIERS if d.domain == domain), None)
        if (dossier is None or not isinstance(principal, Principal)
                or dossier.role not in principal.roles
                or not isinstance(principal.subject, str)
                or not principal.subject.startswith("synthetic-")):
            raise HandoffNotAuthorized("synthetic domain role required")
        return digest(principal.subject)

    def _append(self, db: sqlite3.Connection, *, principal: Principal,
                domain: str, evidence_id: str, action_id: str, stage: str,
                reference_ref: str, claimed_sha256: str, note_ref: str | None,
                expected_revision: int) -> HandoffEvent:
        actor = self._actor(principal, domain)
        if (not recognized(domain, evidence_id) or not _ref(action_id)
                or not _ref(reference_ref) or not _hex(claimed_sha256)
                or note_ref is not None and not _ref(note_ref)
                or type(expected_revision) is not int):
            raise ValueError("invalid synthetic evidence reference")
        verify_pinned_business_sources()
        with self._transaction() as db:
            events = self._verify(db)
            by_action = next((e for e in events if e.action_id == action_id), None)
            if by_action is not None:
                if (by_action.domain == domain and by_action.evidence_id == evidence_id
                        and by_action.stage == stage and by_action.actor_digest == actor
                        and by_action.reference_ref == reference_ref
                        and by_action.claimed_sha256 == claimed_sha256
                        and by_action.note_ref == note_ref
                        and by_action.revision == expected_revision + 1):
                    return by_action
                raise HandoffConflict("action already used with other input")
            current = next((
                e for e in reversed(events)
                if e.domain == domain and e.evidence_id == evidence_id
            ), None)
            if (expected_revision != (0 if current is None else current.revision)
                    or (stage == STAGES[0] and current is not None)
                    or (stage == STAGES[1] and (
                        current is None or current.stage != STAGES[0]
                        or current.actor_digest == actor
                        or note_ref is None))):
                raise HandoffConflict("unexpected technical review revision")
            if stage == STAGES[1] and not self._review_authorizer(
                principal.subject, domain, evidence_id
            ):
                raise HandoffNotAuthorized("no independent reviewer authority")
            sequence = len(events) + 1
            previous = events[-1].event_digest if events else GENESIS
            raw = {
                "sequence": sequence, "action_id": action_id,
                "domain": domain, "evidence_id": evidence_id,
                "stage": stage, "revision": expected_revision + 1,
                "actor_digest": actor, "reference_ref": reference_ref,
                "claimed_sha256": claimed_sha256, "note_ref": note_ref,
                "previous_digest": previous,
            }
            encoded = canonical(raw)
            stamp = digest(encoded)
            db.execute("INSERT INTO handoff_event VALUES (?, ?, ?, ?, ?)",
                       (sequence, action_id, encoded, stamp, previous))
            db.execute("UPDATE handoff_meta SET value=? WHERE key='head'",
                       (stamp,))
            return HandoffEvent(**raw, event_digest=stamp)

    def record_reference(self, *, principal: Principal, domain: str,
                         evidence_id: str, action_id: str, reference_ref: str,
                         claimed_sha256: str, expected_revision: int = 0) -> HandoffEvent:
        return self._append(
            None, principal=principal, domain=domain, evidence_id=evidence_id,
            action_id=action_id, reference_ref=reference_ref,
            claimed_sha256=claimed_sha256, expected_revision=expected_revision,
            stage=STAGES[0], note_ref=None,
        )

    def record_human_note(self, *, principal: Principal, domain: str,
                          evidence_id: str, action_id: str, reference_ref: str,
                          claimed_sha256: str, note_ref: str,
                          expected_revision: int = 1) -> HandoffEvent:
        return self._append(
            None, principal=principal, domain=domain, evidence_id=evidence_id,
            action_id=action_id, reference_ref=reference_ref,
            claimed_sha256=claimed_sha256, expected_revision=expected_revision,
            stage=STAGES[1], note_ref=note_ref,
        )

    def worklist(self, principal: Principal, domain: str) -> dict:
        self._actor(principal, domain)
        verify_pinned_business_sources()
        with self._transaction() as db:
            events = self._verify(db)
            latest = {(e.domain, e.evidence_id): e for e in events}
            dossier = next(d for d in DOSSIERS if d.domain == domain)
            return {
                "domain": domain, "business_source_sha": BUSINESS_SOURCE_SHA,
                "snapshot_state": "PINNED_DRAFT_SNAPSHOT_NOT_LIVE",
                "items": [
                    latest[(domain, e.evidence_id)].public_status()
                    if (domain, e.evidence_id) in latest else {
                        "domain": domain, "evidence_id": e.evidence_id,
                        "technical_state": "NO_REFERENCE", "review_revision": 0,
                        "gate_status_at_source": "OPEN",
                        "evidence_verified": False, "rights_verified": False,
                        "business_approval": False,
                        "business_source_sha": BUSINESS_SOURCE_SHA,
                        "snapshot_state": "PINNED_DRAFT_SNAPSHOT_NOT_LIVE",
                    }
                    for e in dossier.evidence
                ],
            }

    def verify_integrity(self) -> bool:
        try:
            verify_pinned_business_sources()
            with self._transaction() as db:
                self._verify(db)
            return True
        except (HandoffIntegrityError, sqlite3.Error):
            return False
