"""Transactional, restart-safe SYNTHETIC record-grant ledger (local-only).

This is a SQLite reference adapter, not a production grant authority, legal
consent store or independently anchored audit service. No HTTP grant mutation
exists. Every permitted read and grant revocation is serialized with its audit
event; corrupted audit or changed seed data fails closed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Callable, Iterable, Iterator

from .auth import Principal
from .scoped_audit import AuditEntry, GrantConflict, GrantNotAuthorized
from .scoped_drafts import (
    ENGINES, ScopedDraft, ScopedSyntheticDraftRegistry,
    _OP_ROLE, _synthetic_ref, _synthetic_subject,
)

GENESIS = "0" * 64
REVOCATION_COMMAND_MODE = "REVOCATION_COMMAND_SHA256:"


class LedgerIntegrityError(ValueError):
    """Database history or current grants cannot be trusted."""


def _hash(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _json(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class SqliteSyntheticGrantLedger(ScopedSyntheticDraftRegistry):
    """Single-host durable *test/reference* record authorization adapter."""

    def __init__(self, path: str | Path, records: Iterable[ScopedDraft], *,
                 previous_versions: Iterable[ScopedDraft] = (),
                 trusted_revoke_authorizer: Callable[[str, str, str], bool]):
        if not callable(trusted_revoke_authorizer):
            raise ValueError("independent trusted synthetic authorizer required")
        super().__init__(records)
        self.path = Path(path)
        if not self.path.is_absolute() or self.path.is_symlink() or not self.path.parent.is_dir():
            raise ValueError("absolute regular local database path required")
        self._authorizer = trusted_revoke_authorizer
        histories = {key: [record.version] for key, record in self._catalogue.items()}
        fingerprints = []
        for (engine, ref), r in sorted(self._catalogue.items()):
            fingerprints.append({
                "engine": engine, "ref": ref, "owner": r.owner_subject,
                "version": r.version, "source_ref": r.source_ref,
                "grants": sorted((g.subject, g.role) for g in r.grants),
            })
        for old in previous_versions:
            if not isinstance(old, ScopedDraft):
                raise ValueError("immutable synthetic previous version required")
            key = (old.engine, old.ref)
            current = self._catalogue.get(key)
            if (current is None or old.version >= current.version
                    or old.owner_subject != current.owner_subject):
                raise ValueError("invalid prior case version or ownership")
            histories[key].append(old.version)
        self._histories = {}
        for key, versions in histories.items():
            if len(versions) != len(set(versions)):
                raise ValueError("duplicate historical case version")
            self._histories[key] = tuple(sorted(versions))
        self._fingerprint = _hash(_json({
            "cases": fingerprints,
            "versions": [[k[0], k[1], list(v)] for k, v in sorted(self._histories.items())],
        }))
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if self.path.is_symlink():
                raise ValueError("symlink database forbidden") from None
        else:
            os.close(fd)
        info = self.path.stat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077
                or hasattr(os, "getuid") and info.st_uid != os.getuid()):
            raise ValueError("grant ledger must be owned, private regular file")
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS case_revision (
                    engine TEXT NOT NULL, ref TEXT NOT NULL, revision INTEGER NOT NULL,
                    PRIMARY KEY(engine, ref)
                );
                CREATE TABLE IF NOT EXISTS case_history (
                    engine TEXT NOT NULL, ref TEXT NOT NULL, version INTEGER NOT NULL,
                    PRIMARY KEY(engine, ref, version)
                );
                CREATE TABLE IF NOT EXISTS grant_revocation (
                    action_id TEXT PRIMARY KEY, engine TEXT NOT NULL, ref TEXT NOT NULL,
                    subject_digest TEXT NOT NULL, role TEXT NOT NULL,
                    payload_digest TEXT NOT NULL, event_sequence INTEGER UNIQUE NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_event (
                    sequence INTEGER PRIMARY KEY, previous_digest TEXT NOT NULL,
                    digest TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_event
                BEGIN SELECT RAISE(ABORT, 'append only audit'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_event
                BEGIN SELECT RAISE(ABORT, 'append only audit'); END;
                CREATE TRIGGER IF NOT EXISTS revocation_no_update BEFORE UPDATE ON grant_revocation
                BEGIN SELECT RAISE(ABORT, 'revocation immutable'); END;
                CREATE TRIGGER IF NOT EXISTS revocation_no_delete BEFORE DELETE ON grant_revocation
                BEGIN SELECT RAISE(ABORT, 'revocation immutable'); END;
                CREATE TRIGGER IF NOT EXISTS case_history_no_update BEFORE UPDATE ON case_history
                BEGIN SELECT RAISE(ABORT, 'history immutable'); END;
                CREATE TRIGGER IF NOT EXISTS case_history_no_delete BEFORE DELETE ON case_history
                BEGIN SELECT RAISE(ABORT, 'history immutable'); END;
            """)
        with self._transaction() as db:
            identity = db.execute(
                "SELECT value FROM metadata WHERE key='fingerprint'"
            ).fetchone()
            if identity is None:
                if (db.execute("SELECT COUNT(*) FROM audit_event").fetchone()[0] != 0
                        or db.execute("SELECT COUNT(*) FROM grant_revocation").fetchone()[0] != 0
                        or db.execute("SELECT COUNT(*) FROM case_revision").fetchone()[0] != 0):
                    raise LedgerIntegrityError("partial or untrusted ledger bootstrap")
                db.execute("INSERT INTO metadata VALUES ('fingerprint', ?)", (self._fingerprint,))
                db.execute("INSERT INTO metadata VALUES ('head_digest', ?)", (GENESIS,))
                for engine, ref in self._catalogue:
                    db.execute("INSERT INTO case_revision VALUES (?, ?, 0)", (engine, ref))
                    for version in self._histories[(engine, ref)]:
                        db.execute("INSERT INTO case_history VALUES (?, ?, ?)",
                                   (engine, ref, version))
            elif identity[0] != self._fingerprint:
                raise LedgerIntegrityError("seeded case/grant definition changed")
            self._verify(db)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=15, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=15000")
            db.execute("PRAGMA secure_delete=ON")
            db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def _verify(self, db: sqlite3.Connection) -> None:
        metadata = dict(db.execute("SELECT key, value FROM metadata"))
        if (set(metadata) != {"fingerprint", "head_digest"}
                or metadata["fingerprint"] != self._fingerprint):
            raise LedgerIntegrityError("ledger identity is untrusted")
        current = dict(
            ((engine, ref), revision)
            for engine, ref, revision in db.execute(
                "SELECT engine, ref, revision FROM case_revision"
            )
        )
        if set(current) != set(self._catalogue):
            raise LedgerIntegrityError("unexpected case scope or missing revision")
        history = {}
        for engine, ref, version in db.execute(
            "SELECT engine, ref, version FROM case_history"
        ):
            history.setdefault((engine, ref), []).append(version)
        if {k: tuple(sorted(v)) for k, v in history.items()} != self._histories:
            raise LedgerIntegrityError("historical version seed mismatch")
        previous = GENESIS
        revoke_events = {}
        # Exact, ordered, per-case audit revision lineage. Read and technical
        # evidence events use the current count; revocation advances it once.
        audit_revisions = {key: 0 for key in self._catalogue}
        for expected, (seq, preceding, digest, payload) in enumerate(
            db.execute("SELECT sequence, previous_digest, digest, payload "
                       "FROM audit_event ORDER BY sequence"), 1
        ):
            try:
                data = json.loads(payload)
                event = AuditEntry(**data)
            except (TypeError, ValueError, KeyError) as exc:
                raise LedgerIntegrityError("malformed audit entry") from exc
            if (seq != expected or preceding != previous
                    or event.sequence != seq or event.previous_digest != preceding
                    or event.digest != digest or _hash(event.canonical().decode()) != digest
                    or (event.engine, event.ref) not in self._catalogue):
                raise LedgerIntegrityError("audit chain mismatch")
            key = (event.engine, event.ref)
            next_revision = audit_revisions[key] + (event.kind == "GRANT_REVOKED")
            if (event.case_version != self._catalogue[key].version
                    or type(event.grant_revision) is not int
                    or event.grant_revision != next_revision):
                raise LedgerIntegrityError("audit case/version/revision lineage mismatch")
            audit_revisions[key] = next_revision
            if event.kind == "GRANT_REVOKED":
                if not event.action_id or event.action_id in revoke_events:
                    raise LedgerIntegrityError("duplicate audit revoke action")
                revoke_events[event.action_id] = event
            elif event.kind in ("TECH_REVIEW_REQUESTED", "TECH_HUMAN_RESPONSE_RECORDED"):
                # A base ledger must never ignore review actions without their
                # coupled review-history consistency verifier.
                if type(self) is SqliteSyntheticGrantLedger:
                    raise LedgerIntegrityError("review events require review-aware ledger")
            elif event.kind not in ("READ_ALLOWED", "READ_DENIED"):
                raise LedgerIntegrityError("unsupported audit event")
            previous = digest
        if metadata["head_digest"] != previous:
            raise LedgerIntegrityError("audit head mismatch")
        revocations = {}
        count = {key: 0 for key in self._catalogue}
        for (action, engine, ref, subject_digest, role, payload_digest, sequence) in db.execute(
            "SELECT action_id, engine, ref, subject_digest, role, payload_digest, "
            "event_sequence FROM grant_revocation"
        ):
            key = (engine, ref)
            event = revoke_events.get(action)
            if (key not in count or role != _OP_ROLE[engine]
                    or event is None or event.sequence != sequence
                    or event.engine != engine or event.ref != ref
                    or event.target_digest != subject_digest
                    or not isinstance(subject_digest, str) or len(subject_digest) != 64
                    or not isinstance(payload_digest, str) or len(payload_digest) != 64
                    or event.access_mode != REVOCATION_COMMAND_MODE + payload_digest
                    or not _synthetic_ref(event.reason_ref)
                    or not any(
                        _hash(g.subject) == subject_digest and g.role == role
                        for g in self._catalogue[key].grants
                    )):
                raise LedgerIntegrityError("revocation and audit disagree")
            count[key] += 1
            if action in revocations:
                raise LedgerIntegrityError("duplicate durable revocation")
            revocations[action] = event
        if set(revocations) != set(revoke_events) or current != count:
            raise LedgerIntegrityError("grant revision no longer matches audit")
        # Additional consistency: there may be no duplicate subject revocations.
        duplicates = db.execute(
            "SELECT 1 FROM grant_revocation GROUP BY engine,ref,subject_digest,role "
            "HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicates:
            raise LedgerIntegrityError("same grant revoked more than once")

    def _append(self, db: sqlite3.Connection, *, kind: str, engine: str,
                ref: str, actor: str, target: str | None = None,
                action_id: str | None = None, reason_ref: str | None = None,
                mode: str | None = None) -> AuditEntry:
        last = db.execute(
            "SELECT sequence, digest FROM audit_event ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence, preceding = (last[0] + 1, last[1]) if last else (1, GENESIS)
        revision = db.execute(
            "SELECT revision FROM case_revision WHERE engine=? AND ref=?",
            (engine, ref),
        ).fetchone()[0]
        stub = AuditEntry(
            sequence, preceding, "", kind, engine, ref, _hash(actor),
            _hash(target) if target else None,
            self._catalogue[(engine, ref)].version, revision,
            action_id, reason_ref, mode,
        )
        digest = _hash(stub.canonical().decode())
        event = AuditEntry(
            stub.sequence, stub.previous_digest, digest, stub.kind,
            stub.engine, stub.ref, stub.actor_digest, stub.target_digest,
            stub.case_version, stub.grant_revision, stub.action_id,
            stub.reason_ref, stub.access_mode,
        )
        db.execute(
            "INSERT INTO audit_event VALUES (?, ?, ?, ?)",
            (sequence, preceding, digest, _json(asdict(event))),
        )
        db.execute("UPDATE metadata SET value=? WHERE key='head_digest'", (digest,))
        return event

    def read(self, engine: str, ref: str, principal: Principal, *,
             as_owner: bool) -> dict | None:
        with self._transaction() as db:
            self._verify(db)
            if (engine not in ENGINES or not _synthetic_ref(ref)
                    or (engine, ref) not in self._catalogue
                    or not isinstance(principal, Principal)
                    or not _synthetic_subject(principal.subject)):
                return None
            result = super().read(engine, ref, principal, as_owner=as_owner)
            if result is not None and not as_owner:
                role = _OP_ROLE[engine]
                row = db.execute(
                    "SELECT 1 FROM grant_revocation WHERE engine=? AND ref=? "
                    "AND subject_digest=? AND role=?",
                    (engine, ref, _hash(principal.subject), role),
                ).fetchone()
                if row:
                    result = None
            self._append(
                db, kind="READ_ALLOWED" if result is not None else "READ_DENIED",
                engine=engine, ref=ref, actor=principal.subject,
                mode="OWNER" if as_owner else "OPERATIONS",
            )
            return result

    def list_owned_domestic_drafts(
        self, principal: Principal, *, after_ref: str | None = None,
        limit: int = 20,
    ) -> dict:
        """List the caller's own synthetic household cases, never staff grants.

        Only a preverified household subject can see its exact immutable
        Domestic fixture ownership. The same BEGIN IMMEDIATE checks ledger
        integrity and appends an owner audit event for every returned item;
        a failed append rolls back the entire page. Cross-household and
        Export identifiers and global counts are never returned.
        """
        if (type(limit) is not int or not 1 <= limit <= 50
                or after_ref is not None and not _synthetic_ref(after_ref)):
            raise ValueError("invalid synthetic owner list query")
        with self._transaction() as db:
            self._verify(db)
            results: list[dict] = []
            next_cursor = None
            if (isinstance(principal, Principal)
                    and _synthetic_subject(principal.subject)
                    and "household" in principal.roles):
                owned = [
                    ref for (engine, ref), record in sorted(self._catalogue.items())
                    if engine == "DOMESTIC"
                    and record.owner_subject == principal.subject
                    and (after_ref is None or ref > after_ref)
                ]
                for ref in owned[:limit]:
                    record = self._catalogue[("DOMESTIC", ref)]
                    results.append(record.public_view())
                    self._append(
                        db, kind="READ_ALLOWED", engine="DOMESTIC",
                        ref=ref, actor=principal.subject,
                        mode="HOUSEHOLD_OWNED_WORKLIST",
                    )
                if len(owned) > limit:
                    next_cursor = results[-1]["ref"]
            return {
                "engine": "DOMESTIC",
                "items": results,
                "next_cursor": next_cursor,
            }

    def revoke_grant(self, *, engine: str, ref: str, subject: str, role: str,
                     actor: str, expected_grant_revision: int,
                     action_id: str, reason_ref: str) -> AuditEntry:
        if (engine not in ENGINES or not _synthetic_ref(ref)
                or not _synthetic_subject(subject) or not _synthetic_subject(actor)
                or role != _OP_ROLE[engine]
                or type(expected_grant_revision) is not int
                or expected_grant_revision < 0
                or not _synthetic_ref(action_id) or not _synthetic_ref(reason_ref)):
            raise ValueError("invalid synthetic revocation")
        payload = _hash(_json({
            "engine": engine, "ref": ref, "subject": subject, "role": role,
            "actor": actor, "expected_grant_revision": expected_grant_revision,
            "reason_ref": reason_ref,
        }))
        with self._transaction() as db:
            self._verify(db)
            record = self._catalogue.get((engine, ref))
            if record is None:
                raise GrantConflict("unknown synthetic case")
            try:
                authorized = self._authorizer(actor, engine, ref)
            except Exception as exc:
                raise GrantNotAuthorized("trusted authority failed") from exc
            if authorized is not True:
                raise GrantNotAuthorized("independent approval required")
            replay = db.execute(
                "SELECT payload_digest, event_sequence FROM grant_revocation WHERE action_id=?",
                (action_id,),
            ).fetchone()
            if replay:
                if replay[0] != payload:
                    raise GrantConflict("conflicting replay")
                row = db.execute("SELECT payload FROM audit_event WHERE sequence=?",
                                 (replay[1],)).fetchone()
                if row is None:
                    raise LedgerIntegrityError("revocation audit missing")
                return AuditEntry(**json.loads(row[0]))
            revision = db.execute(
                "SELECT revision FROM case_revision WHERE engine=? AND ref=?",
                (engine, ref),
            ).fetchone()[0]
            if expected_grant_revision != revision:
                raise GrantConflict("stale expected grant revision")
            if not any(g.subject == subject and g.role == role for g in record.grants):
                raise GrantConflict("grant not pre-seeded")
            already = db.execute(
                "SELECT 1 FROM grant_revocation WHERE engine=? AND ref=? "
                "AND subject_digest=? AND role=?",
                (engine, ref, _hash(subject), role),
            ).fetchone()
            if already:
                raise GrantConflict("grant already revoked")
            db.execute(
                "UPDATE case_revision SET revision=revision+1 WHERE engine=? AND ref=?",
                (engine, ref),
            )
            event = self._append(
                db, kind="GRANT_REVOKED", engine=engine, ref=ref,
                actor=actor, target=subject, action_id=action_id,
                reason_ref=reason_ref, mode=REVOCATION_COMMAND_MODE + payload,
            )
            db.execute(
                "INSERT INTO grant_revocation VALUES (?, ?, ?, ?, ?, ?, ?)",
                (action_id, engine, ref, _hash(subject), role, payload, event.sequence),
            )
            return event

    def grant_revision(self, engine: str, ref: str) -> int | None:
        with self._transaction() as db:
            self._verify(db)
            row = db.execute(
                "SELECT revision FROM case_revision WHERE engine=? AND ref=?",
                (engine, ref),
            ).fetchone()
            return row[0] if row else None

    def case_versions(self, engine: str, ref: str) -> tuple[int, ...]:
        with self._transaction() as db:
            self._verify(db)
            return tuple(row[0] for row in db.execute(
                "SELECT version FROM case_history WHERE engine=? AND ref=? ORDER BY version",
                (engine, ref),
            ))

    def audit_snapshot(self) -> tuple[AuditEntry, ...]:
        with self._transaction() as db:
            self._verify(db)
            return tuple(AuditEntry(**json.loads(row[0])) for row in db.execute(
                "SELECT payload FROM audit_event ORDER BY sequence"
            ))

    def verify_integrity(self) -> bool:
        try:
            with self._transaction() as db:
                self._verify(db)
            return True
        except (LedgerIntegrityError, sqlite3.DatabaseError, ValueError, TypeError):
            return False
