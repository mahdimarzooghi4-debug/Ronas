"""Immutable LOCAL/TEST candidate knowledge catalogue, never an attestation.

The immutable event list can be rebuilt and compared without exposing source
content. No real files, rights, scientific decisions or model training exist.
This is NOT a persistent authoritative register or a production importer.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from .internal_scientific_basis_contract import (
    ScientificBasisCandidate, ScientificSourceCandidate,
    inspect_scientific_basis_structure,
)
from .scoped_drafts import _synthetic_ref

CONTRACT_VERSION = "ronas.domestic.synthetic-source-catalogue-history.v0"
RECORDED = "CANDIDATE_VERSION_RECORDED_UNVERIFIED"
WITHHELD = "CANDIDATE_WITHHELD_FROM_NEW_SYNTHETIC_USE"
OPERATIONS = frozenset((RECORDED, WITHHELD))


@dataclass(frozen=True, slots=True)
class SyntheticSourceCatalogueEvent:
    """One explicit synthetic revision. No actor signature/rights clearance."""

    action_ref: str
    source_ref: str
    source_revision: int
    operation: str
    candidate: ScientificSourceCandidate | None = None
    reason_ref: str | None = None

    def __post_init__(self):
        if (not _synthetic_ref(self.action_ref)
                or not _synthetic_ref(self.source_ref)
                or type(self.source_revision) is not int
                or self.source_revision < 1
                or self.operation not in OPERATIONS):
            raise ValueError("invalid synthetic knowledge catalogue event")
        if self.operation == RECORDED:
            if (not isinstance(self.candidate, ScientificSourceCandidate)
                    or self.candidate.ref != self.source_ref
                    or self.candidate.version != self.source_revision
                    or self.reason_ref is not None):
                raise ValueError("recorded source must carry matching candidate version")
        elif (self.candidate is not None
              or not _synthetic_ref(self.reason_ref)):
            raise ValueError("withholding requires an explicit DEMO reason pointer")


def _canonical(event: SyntheticSourceCatalogueEvent) -> tuple:
    c = event.candidate
    return (
        event.action_ref, event.source_ref, event.source_revision,
        event.operation, event.reason_ref,
        None if c is None else (
            c.ref, c.version, c.content_sha256, c.rights_document_ref,
            c.rights_document_sha256, c.science_review_request_ref,
            c.science_review_material_sha256, c.purpose, c.status,
        ),
    )


@dataclass(frozen=True, slots=True)
class SyntheticScientificCatalogue:
    """Validated, immutable, ordered catalogue of LOCAL/TEST source events.

    Caller supplies history through trusted test configuration. There is no
    write API, no concurrent durable store and no role self-qualification.
    """

    events: tuple[SyntheticSourceCatalogueEvent, ...] = ()

    def __post_init__(self):
        if (type(self.events) is not tuple
                or any(not isinstance(e, SyntheticSourceCatalogueEvent)
                       for e in self.events)):
            raise ValueError("invalid synthetic knowledge catalogue history")
        revisions: dict[str, int] = {}
        latest: dict[str, ScientificSourceCandidate | None] = {}
        actions: set[str] = set()
        for event in self.events:
            old = revisions.get(event.source_ref, 0)
            previous = latest.get(event.source_ref)
            if (event.action_ref in actions
                    or event.source_revision != old + 1
                    or event.operation == WITHHELD and (
                        old == 0 or previous is None
                    )
                    or event.operation == RECORDED
                    and previous is not None
                    and _same_material(previous, event.candidate)):
                raise ValueError("duplicate, stale, no-op or invalid source revision")
            actions.add(event.action_ref)
            revisions[event.source_ref] = event.source_revision
            latest[event.source_ref] = event.candidate

    @property
    def revision(self) -> int:
        return len(self.events)

    def with_event(self, event: SyntheticSourceCatalogueEvent) -> SyntheticScientificCatalogue:
        """Pure copy-on-write. Never modifies previous snapshots."""
        return SyntheticScientificCatalogue(self.events + (event,))

    def _current(self) -> dict[str, ScientificSourceCandidate]:
        current: dict[str, ScientificSourceCandidate] = {}
        for item in self.events:
            if item.operation == RECORDED:
                current[item.source_ref] = item.candidate
            else:
                current.pop(item.source_ref, None)
        return current

    def current_sources(self) -> tuple[ScientificSourceCandidate, ...]:
        """Typed internal snapshot for existing *synthetic-only* source checks."""
        current = self._current()
        return tuple(current[ref] for ref in sorted(current))

    def snapshot_at(self, revision: int) -> SyntheticScientificCatalogue:
        """Historical **structural** view, never passed as current authority."""
        if (type(revision) is not int or revision < 0
                or revision > len(self.events)):
            raise ValueError("unknown knowledge catalogue history revision")
        return SyntheticScientificCatalogue(self.events[:revision])

    @property
    def fingerprint(self) -> str:
        """Deterministic, version-separated hash. Not a signature or proof."""
        data = {
            "contract": CONTRACT_VERSION,
            "event_sequence": [_canonical(e) for e in self.events],
        }
        return sha256(json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("ascii")).hexdigest()

    def redacted_summary(self) -> dict:
        return {
            "contract_version": CONTRACT_VERSION,
            "catalogue_state": "SYNTHETIC_SOURCE_POINTER_HISTORY_ONLY",
            "catalogue_revision": self.revision,
            "current_source_candidate_count": len(self.current_sources()),
            "historical_event_count": len(self.events),
            "history_fingerprint_sha256": self.fingerprint,
            "source_bytes_attested": False,
            "rights_for_cultivation_service_verified": False,
            "rights_for_ai_training_verified": False,
            "scientific_suitability_verified": False,
            "qualified_specialist_verified": False,
            "approval_or_new_advice_authorized": False,
            "real_data": False,
        }

    def inspect_basis_candidate(self, basis: ScientificBasisCandidate) -> dict:
        """Pin against CURRENT typed candidates, fail closed for withdrawn/drift."""
        if not isinstance(basis, ScientificBasisCandidate):
            raise ValueError("untrusted scientific basis candidate")
        return inspect_scientific_basis_structure(
            basis, expected_manifest_digest=basis.manifest_digest,
            current_sources=self.current_sources(),
        )

    def compare(self, earlier_revision: int, later_revision: int) -> dict:
        """Only candidate-revision changes; no source or rights-doc IDs leaked."""
        if (type(earlier_revision) is not int
                or type(later_revision) is not int
                or not 0 <= earlier_revision < later_revision <= self.revision):
            raise ValueError("invalid synthetic science catalogue comparison")
        old = self.snapshot_at(earlier_revision)
        new = self.snapshot_at(later_revision)
        before, after = old._current(), new._current()
        added = set(after) - set(before)
        withheld = set(before) - set(after)
        changed = set(before) & set(after)
        content = rights = science = version_only = 0
        for ref in changed:
            a, b = before[ref], after[ref]
            if a.content_sha256 != b.content_sha256:
                content += 1
            if ((a.rights_document_ref, a.rights_document_sha256)
                    != (b.rights_document_ref, b.rights_document_sha256)):
                rights += 1
            if ((a.science_review_request_ref,
                  a.science_review_material_sha256)
                    != (b.science_review_request_ref,
                        b.science_review_material_sha256)):
                science += 1
            if (a.version != b.version and
                    a.content_sha256 == b.content_sha256
                    and a.rights_document_ref == b.rights_document_ref
                    and a.rights_document_sha256 == b.rights_document_sha256
                    and a.science_review_request_ref == b.science_review_request_ref
                    and a.science_review_material_sha256
                        == b.science_review_material_sha256):
                version_only += 1
        return {
            "contract_version": CONTRACT_VERSION,
            "comparison_scope": "SYNTHETIC_UNVERIFIED_CANDIDATE_POINTERS_ONLY",
            "from_revision": earlier_revision,
            "to_revision": later_revision,
            "from_history_fingerprint_sha256": old.fingerprint,
            "to_history_fingerprint_sha256": new.fingerprint,
            "added_candidate_count": len(added),
            "withheld_candidate_count": len(withheld),
            "changed_content_pointer_count": content,
            "changed_service_rights_document_pointer_count": rights,
            "changed_science_review_material_pointer_count": science,
            "changed_version_only_count": version_only,
            "historical_record_deleted": False,
            "source_bytes_attested": False,
            "service_use_rights_verified": False,
            "ai_training_rights_verified": False,
            "scientific_validity_verified": False,
            "expert_decision_recorded": False,
            "new_advice_enabled": False,
            "real_data": False,
        }


def _same_material(
    previous: ScientificSourceCandidate,
    next_candidate: ScientificSourceCandidate,
) -> bool:
    """Version-only no-op is still permitted when the revision is explicit."""
    # Explicit revision has lineage value; caller must not invent evidence
    # from a number. The catalogue never confers eligibility as a result.
    return previous == next_candidate
