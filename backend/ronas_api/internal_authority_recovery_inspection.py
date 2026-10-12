"""Read-only classification of LOCAL/TEST journal/checkpoint recovery state.

An observation is not recovery approval or an atomic lease. Use the existing
assert_current() at the actual point of use; never auto-create or auto-pin.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

from .grant_ledger_sqlite import LedgerIntegrityError
from .internal_authority_revision_journal_sqlite import (
    GENESIS, SqliteSyntheticAuthorityRevisionJournal,
)
from .internal_authority_local_checkpoint_sqlite import (
    LocalCheckpointMismatch, SqliteLocalAuthorityCheckpoint,
)

MATCHED = "MATCHED"
MISSING_BOTH = "BOTH_FILES_MISSING"
MISSING_JOURNAL = "JOURNAL_MISSING"
MISSING_CHECKPOINT = "CHECKPOINT_MISSING"
JOURNAL_UNTRUSTED = "JOURNAL_UNTRUSTED"
CHECKPOINT_UNTRUSTED = "CHECKPOINT_UNTRUSTED"
NO_CHECKPOINT = "CHECKPOINT_NOT_PINNED"
REPLACED = "JOURNAL_INSTANCE_MISMATCH"
BEHIND = "JOURNAL_BEHIND_CHECKPOINT"
AHEAD = "JOURNAL_AHEAD_UNPINNED"
DIVERGED = "JOURNAL_HISTORY_DIVERGED"
STATES = frozenset((
    MATCHED,MISSING_BOTH,MISSING_JOURNAL,MISSING_CHECKPOINT,
    JOURNAL_UNTRUSTED,CHECKPOINT_UNTRUSTED,NO_CHECKPOINT,
    REPLACED,BEHIND,AHEAD,DIVERGED,
))


@dataclass(frozen=True, slots=True)
class LocalRecoveryAssessment:
    state: str
    local_checkpoint_matches: bool
    independent_external_attestation: bool = False

    def __post_init__(self):
        if (self.state not in STATES
                or type(self.local_checkpoint_matches) is not bool
                or self.local_checkpoint_matches != (self.state == MATCHED)
                or self.independent_external_attestation is not False):
            raise ValueError("untrusted recovery assessment")


def inspect_local_recovery(
    journal_path: str | Path, checkpoint_path: str | Path,
) -> LocalRecoveryAssessment:
    """Never creates files, modifies journal state or pins any trust record.

    Returns local-only state of two *separately held* files. It cannot prove
    that two mutually coherent files weren't both rolled back together.
    """
    jpath, cpath = Path(journal_path), Path(checkpoint_path)
    if (not jpath.is_absolute() or not cpath.is_absolute()
            or jpath.resolve() == cpath.resolve()):
        raise ValueError("recovery inspection requires distinct absolute paths")
    if not jpath.exists() and not cpath.exists():
        return LocalRecoveryAssessment(MISSING_BOTH,False)
    if not jpath.exists():
        return LocalRecoveryAssessment(MISSING_JOURNAL,False)
    if not cpath.exists():
        return LocalRecoveryAssessment(MISSING_CHECKPOINT,False)
    try:
        journal = SqliteSyntheticAuthorityRevisionJournal.open_existing(jpath)
    except (LedgerIntegrityError, sqlite3.DatabaseError, ValueError, OSError):
        return LocalRecoveryAssessment(JOURNAL_UNTRUSTED,False)
    try:
        checkpoint = SqliteLocalAuthorityCheckpoint.open_existing(cpath)
    except (LocalCheckpointMismatch, sqlite3.DatabaseError, ValueError, OSError):
        return LocalRecoveryAssessment(CHECKPOINT_UNTRUSTED,False)
    try:
        with journal._transaction() as source:
            current = checkpoint._journal_position(source,journal)
            with checkpoint._tx() as side:
                pinned, _, _ = checkpoint._verify(side)
                if pinned is None:
                    state = NO_CHECKPOINT
                elif current[0] != pinned[0]:
                    state = REPLACED
                elif current[1] < pinned[1]:
                    state = BEHIND
                elif current[1] == pinned[1]:
                    state = MATCHED if current[2] == pinned[2] else DIVERGED
                else:
                    ancestor = (
                        GENESIS if pinned[1] == 0
                        else (
                            (row := source.execute(
                                "SELECT event_digest FROM authority_event "
                                "WHERE sequence=?", (pinned[1],)
                            ).fetchone()) and row[0]
                        )
                    )
                    state = AHEAD if ancestor == pinned[2] else DIVERGED
    except (LedgerIntegrityError, sqlite3.DatabaseError, ValueError, OSError):
        return LocalRecoveryAssessment(JOURNAL_UNTRUSTED,False)
    return LocalRecoveryAssessment(state,state == MATCHED)
