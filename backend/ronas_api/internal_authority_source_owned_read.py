"""Opt-in source-owned observation protocol for synthetic specialist reads.

A provider callback returns its current scoped typed candidate snapshot AND
its source-owned monotonic generation together. The provider, not this helper,
must guarantee these were read from one locally consistent owner transaction.
The protocol does not attest that claim, coordinate independent providers,
grant scope, establish professional qualification or enable Production.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Callable

from .grant_ledger_sqlite import LedgerIntegrityError
from .internal_authority_revision_journal_sqlite import snapshot_digest
from .internal_authority_revision_witness import (
    KINDS, SyntheticAuthorityWitness, validate_witness_vector,
)

VERSION = "ronas.domestic.source-owned-candidate-observation.v0"


@dataclass(frozen=True, slots=True)
class SourceOwnedCandidateObservation:
    witness: SyntheticAuthorityWitness
    snapshot: object
    snapshot_digest_sha256: str

    def __post_init__(self) -> None:
        if (type(self.witness) is not SyntheticAuthorityWitness
                or self.witness.generation < 1
                or type(self.snapshot_digest_sha256) is not str):
            raise ValueError("missing source-owned candidate generation or digest")
        w = self.witness
        actual = snapshot_digest(
            w.kind, w.subject, w.case_ref, w.case_version, self.snapshot,
        )
        if actual != self.snapshot_digest_sha256:
            raise ValueError("owner candidate snapshot and revision disagree")


@dataclass(frozen=True, slots=True)
class SourceOwnedCandidateAuthorityRead:
    scientific_source: Callable[[str, str, int], SourceOwnedCandidateObservation]
    specialist_evidence: Callable[[str, str, int], SourceOwnedCandidateObservation]
    current_assignment: Callable[[str, str, int], SourceOwnedCandidateObservation]

    def __post_init__(self) -> None:
        if not all(callable(c) for c in (
                self.scientific_source, self.specialist_evidence,
                self.current_assignment)):
            raise ValueError("all source owners must have explicit read callbacks")

    def observations(
        self, subject: str, case_ref: str, case_version: int,
    ) -> tuple[SourceOwnedCandidateObservation, ...]:
        """One typed read per owner; no decoupled counter-only fallback."""
        try:
            observed = tuple(c(subject, case_ref, case_version) for c in (
                self.scientific_source, self.specialist_evidence,
                self.current_assignment,
            ))
            _validate_observations(
                observed, subject=subject, case_ref=case_ref,
                case_version=case_version,
            )
            return observed
        except Exception as exc:
            raise LedgerIntegrityError(
                "source-owned candidate observations unavailable"
            ) from exc


def _validate_observations(observed, *, subject, case_ref, case_version):
    if (type(observed) is not tuple or len(observed) != len(KINDS)
            or any(type(o) is not SourceOwnedCandidateObservation
                   for o in observed)):
        raise ValueError("invalid source-owner observation collection")
    validate_witness_vector(
        tuple(o.witness for o in observed),
        subject=subject, case_ref=case_ref, case_version=case_version,
    )
    for observation in observed:
        w = observation.witness
        if snapshot_digest(
            w.kind, subject, case_ref, case_version, observation.snapshot,
        ) != observation.snapshot_digest_sha256:
            raise ValueError("source-owner snapshot mutated after observation")
    return observed


def compare_owned_observations(first, second, *, subject, case_ref, case_version):
    """Reject generation drift, content drift, and same-content ABA."""
    try:
        _validate_observations(
            first, subject=subject, case_ref=case_ref,
            case_version=case_version,
        )
        _validate_observations(
            second, subject=subject, case_ref=case_ref,
            case_version=case_version,
        )
        if any(
            (a.witness, a.snapshot_digest_sha256)
            != (b.witness, b.snapshot_digest_sha256)
            for a, b in zip(first, second)
        ):
            raise ValueError("owner candidate generation or content changed")
    except Exception as exc:
        raise LedgerIntegrityError(
            "in-flight source-owned candidate observation drift"
        ) from exc


def source_owned_context_fingerprint(*, versioned_fingerprint, observations):
    """Opaque case fingerprint; never expose owner payloads or hash values."""
    if (type(versioned_fingerprint) is not str
            or len(versioned_fingerprint) != 64
            or any(c not in "0123456789abcdef"
                   for c in versioned_fingerprint)):
        raise LedgerIntegrityError("invalid observed context fingerprint")
    if (type(observations) is not tuple or len(observations) != len(KINDS)
            or any(type(o) is not SourceOwnedCandidateObservation
                   for o in observations)):
        raise LedgerIntegrityError("invalid owner context identity")
    payload = {
        "contract": VERSION,
        "versioned_context": versioned_fingerprint,
        "scoped_owner_snapshots": [
            (o.witness.kind, o.witness.generation, o.snapshot_digest_sha256)
            for o in observations
        ],
    }
    return sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")).hexdigest()
