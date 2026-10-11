"""Offline LOCAL/TEST provenance for Ronas-INTERNAL agronomy source candidates.

Pure structural lineage. Neither science review nor lawful source rights are
verified here, and no plant/crop instructions or training examples are stored.
RON-DEC-015..021/027..028/033; Business D1-SCI-01 is only proposed.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from .internal_cultivation_plan_contract import _digest
from .scoped_drafts import _synthetic_ref

PURPOSE = "DOMESTIC_CULTIVATION_PLAN"
CONTRACT_VERSION = "ronas.domestic.internal-science-basis-structure.v0"
SOURCE_STATUS = "UNVERIFIED_SOURCE_CANDIDATE"


@dataclass(frozen=True, slots=True)
class ScientificSourceCandidate:
    """A source *reference*, not scientific, legal or model-use authorization."""

    ref: str
    version: int
    content_sha256: str
    rights_document_ref: str
    rights_document_sha256: str
    science_review_request_ref: str
    science_review_material_sha256: str
    purpose: str = PURPOSE
    status: str = SOURCE_STATUS

    def __post_init__(self):
        if (not _synthetic_ref(self.ref)
                or type(self.version) is not int or self.version < 1
                or not _digest(self.content_sha256)
                or not _synthetic_ref(self.rights_document_ref)
                or not _digest(self.rights_document_sha256)
                or not _synthetic_ref(self.science_review_request_ref)
                or not _digest(self.science_review_material_sha256)
                or self.purpose != PURPOSE
                or self.status != SOURCE_STATUS):
            raise ValueError("invalid synthetic scientific source candidate")


@dataclass(frozen=True, slots=True)
class ScientificBasisCandidate:
    """Exactly versioned set of unreviewed source pointers, never a plan."""

    ref: str
    version: int
    sources: tuple[ScientificSourceCandidate, ...]
    purpose: str = PURPOSE

    def __post_init__(self):
        if (not _synthetic_ref(self.ref)
                or type(self.version) is not int or self.version < 1
                or type(self.sources) is not tuple or not self.sources
                or any(not isinstance(s, ScientificSourceCandidate)
                       for s in self.sources)
                or len({s.ref for s in self.sources}) != len(self.sources)
                or self.purpose != PURPOSE):
            raise ValueError("invalid science-basis candidate")

    @property
    def manifest_digest(self) -> str:
        """Reproducible fingerprint of version and exact source/rights/review data.

        Hashing does NOT prove the bytes exist or source use is lawful.
        Canonical order prevents a mere order change from changing identity.
        """
        return sha256(json.dumps({
            "contract": CONTRACT_VERSION,
            "basis_ref": self.ref,
            "basis_version": self.version,
            "purpose": self.purpose,
            "sources": [
                (s.ref, s.version, s.content_sha256, s.rights_document_ref,
                 s.rights_document_sha256, s.science_review_request_ref,
                 s.science_review_material_sha256, s.purpose, s.status)
                for s in sorted(self.sources, key=lambda s: s.ref)
            ],
        }, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def inspect_scientific_basis_structure(
    basis: ScientificBasisCandidate, *, expected_manifest_digest: str,
    current_sources: tuple[ScientificSourceCandidate, ...],
) -> dict:
    """Fail closed if the *separately supplied* current source list has drifted.

    The current list must be supplied by a different LOCAL/TEST source-catalog
    authority than the proposal. It is not actual scientific validation or
    attestation of rights. No content or private source refs are returned.
    """
    if (not isinstance(basis, ScientificBasisCandidate)
            or not _digest(expected_manifest_digest)
            or basis.manifest_digest != expected_manifest_digest
            or type(current_sources) is not tuple
            or any(not isinstance(s, ScientificSourceCandidate)
                   for s in current_sources)
            or len({s.ref for s in current_sources}) != len(current_sources)):
        raise ValueError("invalid/stale internal scientific basis candidate")
    catalog = {s.ref: s for s in current_sources}
    if any(catalog.get(s.ref) != s for s in basis.sources):
        # Source absent, replaced, new source revision or modified rights/
        # review document invalidates this basis for NEW structural inspection.
        raise ValueError("current source lineage differs from proposal")
    return {
        "contract_version": CONTRACT_VERSION,
        "purpose": PURPOSE,
        "basis_state": "PROVENANCE_PINNED_UNVERIFIED",
        "basis_revision": basis.version,
        "candidate_source_count": len(basis.sources),
        "scientific_validity_verified": False,
        "source_material_retrieved_and_attested": False,
        "rights_for_household_plan_verified": False,
        "rights_for_ai_training_verified": False,
        "internal_expert_qualification_verified": False,
        "plan_review_approved": False,
        "new_advice_enabled": False,
        "actual_crop_content_present": False,
        "business_gate_passed": False,
    }
