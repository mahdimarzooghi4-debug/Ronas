"""Explicit LOCAL/TEST sidecar checkpoint for the Ronas authority journal.

This is an independently stored *local* observation, not a trusted third-party
anchor, digital signature, external WORM record, or production backup system.
It can detect a journal rollback only if THIS checkpoint survives unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3
import stat
from typing import Iterator

from .grant_ledger_sqlite import LedgerIntegrityError
from .internal_authority_revision_journal_sqlite import (
    GENESIS, SqliteSyntheticAuthorityRevisionJournal, _sha,
)

VERSION = "ronas.domestic.local-authority-checkpoint.v0"


class LocalCheckpointMismatch(LedgerIntegrityError):
    """An explicitly pinned checkpoint does not match the journal."""


class SqliteLocalAuthorityCheckpoint:
    """Separate private SQLite file, explicit pin/advance and strict checks."""

    @classmethod
    def open_existing(cls, path: str | Path):
        """Recovery-only open; never manufacture lost checkpoint trust."""
        return cls(path, create=False)

    def __init__(self, path: str | Path, *, create: bool = True):
        self.path = Path(path)
        if type(create) is not bool:
            raise ValueError("explicit create flag must be boolean")
        self._strict_existing = create is False
        if (not self.path.is_absolute() or self.path.is_symlink()
                or not self.path.parent.is_dir()):
            raise ValueError("absolute private local checkpoint file required")
        if self._strict_existing:
            if not self.path.is_file():
                raise LocalCheckpointMismatch("existing local checkpoint required")
        else:
            try:
                fd = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError:
                if self.path.is_symlink():
                    raise ValueError("symlink checkpoint forbidden") from None
            else:
                os.close(fd)
        st = self.path.stat()
        if (not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077
                or hasattr(os,"getuid") and st.st_uid != os.getuid()):
            raise ValueError("checkpoint must be a private regular file")
        if not self._strict_existing:
            with self._connect() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=FULL")
                db.executescript("""
                CREATE TABLE IF NOT EXISTS local_checkpoint (
                    ordinal INTEGER PRIMARY KEY, journal_id TEXT NOT NULL,
                    event_sequence INTEGER NOT NULL,
                    event_head TEXT NOT NULL, previous_digest TEXT NOT NULL,
                    checkpoint_digest TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS local_checkpoint_no_update
                BEFORE UPDATE ON local_checkpoint BEGIN
                    SELECT RAISE(ABORT,'immutable checkpoint');
                END;
                CREATE TRIGGER IF NOT EXISTS local_checkpoint_no_delete
                BEFORE DELETE ON local_checkpoint BEGIN
                    SELECT RAISE(ABORT,'immutable checkpoint');
                END;
            """)
        try:
            with self._tx() as db:
                self._verify(db)
        except sqlite3.DatabaseError as exc:
            raise LocalCheckpointMismatch("local checkpoint unreadable") from exc

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        if self._strict_existing:
            from urllib.parse import quote
            db = sqlite3.connect(
                "file:" + quote(str(self.path), safe="/") + "?mode=rw",
                uri=True, timeout=15, isolation_level=None,
            )
        else:
            db = sqlite3.connect(
                self.path, timeout=15, isolation_level=None,
            )
        try:
            db.execute("PRAGMA busy_timeout=15000")
            yield db
        finally:
            db.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    @staticmethod
    def _verify(db: sqlite3.Connection):
        triggers = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='local_checkpoint'"
        )}
        if triggers != {"local_checkpoint_no_update",
                        "local_checkpoint_no_delete"}:
            raise LocalCheckpointMismatch("checkpoint immutable triggers missing")
        expected = 0
        previous = GENESIS
        last = None
        for row in db.execute(
            "SELECT ordinal,journal_id,event_sequence,event_head,"
            "previous_digest,checkpoint_digest FROM local_checkpoint "
            "ORDER BY ordinal"
        ):
            ordinal, journal_id, sequence, head, prev, digest = row
            fields = [VERSION,ordinal,journal_id,sequence,head,prev]
            if (type(ordinal) is not int or ordinal != expected+1
                    or type(journal_id) is not str or len(journal_id) != 32
                    or type(sequence) is not int or sequence < 0
                    or type(head) is not str or len(head) != 64
                    or any(c not in "0123456789abcdef" for c in head)
                    or prev != previous or digest != _sha(fields)
                    or last is not None and (
                        journal_id != last[0] or sequence <= last[1]
                    )):
                raise LocalCheckpointMismatch("local checkpoint chain invalid")
            last = (journal_id,sequence,head)
            previous = digest
            expected = ordinal
        return last, expected, previous

    @staticmethod
    def _journal_position(db, journal):
        journal._verify(db)
        meta = dict(db.execute(
            "SELECT key,value FROM authority_metadata"
        ))
        seq = db.execute(
            "SELECT COUNT(*) FROM authority_event"
        ).fetchone()[0]
        return meta["journal_instance_id"],seq,meta["head_digest"]

    @staticmethod
    def _check_files(journal, checkpoint):
        if (not isinstance(journal,SqliteSyntheticAuthorityRevisionJournal)
                or journal.path.resolve() == checkpoint.path.resolve()
                or os.path.samefile(journal.path,checkpoint.path)):
            raise ValueError("checkpoint must be separate from local journal")

    def pin_current(self, journal: SqliteSyntheticAuthorityRevisionJournal):
        """Explicitly seal verified journal head; never auto-heal a rollback.

        Lock order is journal -> checkpoint. Journal is held unchanged until
        sidecar pin commits; failed pin can be retried without mutating journal.
        """
        self._check_files(journal,self)
        with journal._transaction() as source:
            ident, seq, head = self._journal_position(source,journal)
            with self._tx() as anchor:
                latest, ordinal, prev_digest = self._verify(anchor)
                if latest is not None:
                    old_id, old_seq, old_head = latest
                    if ident != old_id or seq < old_seq:
                        raise LocalCheckpointMismatch(
                            "replaced or rolled-back authority journal"
                        )
                    if old_seq == 0:
                        ancestor = GENESIS
                    else:
                        event = source.execute(
                            "SELECT event_digest FROM authority_event "
                            "WHERE sequence=?", (old_seq,)
                        ).fetchone()
                        ancestor = event[0] if event is not None else None
                    if ancestor != old_head:
                        raise LocalCheckpointMismatch(
                            "journal no longer descends from pinned checkpoint"
                        )
                    if seq == old_seq:
                        if head != old_head:
                            raise LocalCheckpointMismatch(
                                "same sequence but changed history"
                            )
                        return {"journal_id":ident,
                                "event_sequence":seq,
                                "event_head_sha256":head,
                                "checkpoint_ordinal":ordinal}
                values = [VERSION,ordinal+1,ident,seq,head,prev_digest]
                anchor.execute(
                    "INSERT INTO local_checkpoint(ordinal,journal_id,"
                    "event_sequence,event_head,previous_digest,checkpoint_digest)"
                    "VALUES(?,?,?,?,?,?)",
                    (ordinal+1,ident,seq,head,prev_digest,_sha(values)),
                )
                self._verify(anchor)
                return {"journal_id":ident,
                        "event_sequence":seq,"event_head_sha256":head,
                        "checkpoint_ordinal":ordinal+1}

    def assert_current(self, journal: SqliteSyntheticAuthorityRevisionJournal):
        """Reject unpinned progress and changed/old/replaced journal files."""
        self._check_files(journal,self)
        with journal._transaction() as source:
            current = self._journal_position(source,journal)
            with self._tx() as anchor:
                latest,ordinal,_ = self._verify(anchor)
                if latest is None or latest != current:
                    raise LocalCheckpointMismatch(
                        "journal unpinned, advanced, replaced or restored"
                    )
                return {"checkpoint_ordinal":ordinal,
                        "event_sequence":current[1],
                        "verified_against_separate_local_file":True,
                        "independent_external_attestation":False}
