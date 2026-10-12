"""Opt-in strictly LOCAL/TEST checkpointed versioned agronomy reader.

Sources and generations are read from the SAME journal-owned synthetic state.
The separate local checkpoint is checked at the actual read boundary, never
created, repaired or silently advanced. No independent/off-host attestation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .grant_ledger_sqlite import LedgerIntegrityError
from .internal_authority_revision_journal_sqlite import (
    SqliteSyntheticAuthorityRevisionJournal,
)
from .internal_authority_local_checkpoint_sqlite import (
    LocalCheckpointMismatch, SqliteLocalAuthorityCheckpoint,
)
from .internal_authority_revision_witness import (
    KINDS, SyntheticAuthorityWitness, validate_witness_vector,
)

@dataclass(frozen=True, slots=True)
class LocalCheckpointedAuthorityRead:
    journal_path: Path
    checkpoint_path: Path

    def __post_init__(self):
        j, c = Path(self.journal_path), Path(self.checkpoint_path)
        if (not j.is_absolute() or not c.is_absolute()
                or j == c or j.resolve() == c.resolve()):
            raise ValueError("separate absolute local authority paths required")
        object.__setattr__(self, "journal_path", j)
        object.__setattr__(self, "checkpoint_path", c)

    def checked_journal(self) -> SqliteSyntheticAuthorityRevisionJournal:
        """Existing files only. Strict source+sidecar match, no reinitialization."""
        try:
            journal = SqliteSyntheticAuthorityRevisionJournal.open_existing(
                self.journal_path,
            )
            checkpoint = SqliteLocalAuthorityCheckpoint.open_existing(
                self.checkpoint_path,
            )
            checkpoint.assert_current(journal)
            return journal
        except (LedgerIntegrityError, ValueError, OSError,
                sqlite3.DatabaseError) as exc:
            raise LedgerIntegrityError(
                "checkpointed local candidate authority unavailable"
            ) from exc

    def snapshot(self, kind: str, subject: str, ref: str, version: int):
        if kind not in KINDS:
            raise LedgerIntegrityError("unknown local synthetic authority kind")
        try:
            journal = self.checked_journal()
            return journal.read_owned_snapshot(
                kind=kind, subject=subject, case_ref=ref, case_version=version,
            )
        except (LedgerIntegrityError, ValueError, OSError,
                sqlite3.DatabaseError) as exc:
            raise LedgerIntegrityError(
                "checkpointed local candidate snapshot unavailable"
            ) from exc

    def vector(self, subject: str, ref: str, version: int):
        """Read all three real LOCAL/TEST generations; never synthesize zero."""
        try:
            journal = self.checked_journal()
            # Read all three within a SINGLE verified SQLite transaction.
            with journal._transaction() as db:
                states = journal._verify(db)
                values = []
                for kind in KINDS:
                    row = db.execute(
                        "SELECT generation FROM authority_owned_state "
                        "WHERE kind=? AND subject=? AND case_ref=? "
                        "AND case_version=?",
                        (kind, subject, ref, version),
                    ).fetchone()
                    if row is None:
                        raise LedgerIntegrityError(
                            "missing owned local authority generation"
                        )
                    values.append(SyntheticAuthorityWitness(
                        kind, subject, ref, version, row[0],
                    ))
                vector = validate_witness_vector(
                    tuple(values), subject=subject, case_ref=ref,
                    case_version=version,
                )
                if any(states.get((w.kind, subject, ref, version), (None,))[0]
                       != w.generation for w in vector):
                    raise LedgerIntegrityError(
                        "local authority vector not bound to event history"
                    )
            self.checked_journal()
            return vector
        except (LedgerIntegrityError, ValueError, OSError,
                sqlite3.DatabaseError) as exc:
            raise LedgerIntegrityError(
                "checkpointed local authority vector unavailable"
            ) from exc
