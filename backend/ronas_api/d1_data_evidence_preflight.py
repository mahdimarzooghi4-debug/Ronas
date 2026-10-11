"""Ronas D1 internal evidence-inventory preflight — completely non-operational.

No actual household data, source document bytes, legal consent, attestation,
professional license, or scientific knowledge are accepted by this module.
An item is a synthetic, *unverified* internal handoff pointer only.

The field inventory and consent wording are still unapproved Business
candidates (RON-DEC-017..021; D1-DATA-01/02). Accordingly no combination
of pointers can establish usable rights, scientific acceptance, AI training
eligibility or a Business Gate PASS.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re

D1_EVIDENCE_IDS = tuple(f"D1-DATA-E{i:02}" for i in range(1, 8))
PURPOSES = ("HOUSEHOLD_CULTIVATION_PLAN", "AI_TRAINING")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
DRAFT_REF = re.compile(r"^DEMO-[A-Z0-9-]{1,48}$")
CONTRACT_VERSION = "ronas.domestic.d1-evidence-preflight.v0"
STATUS = "SUBMITTED_UNVERIFIED"


def _digest(v: object) -> bool:
    return isinstance(v, str) and DIGEST.fullmatch(v) is not None


def _reference(v: object) -> bool:
    return isinstance(v, str) and DRAFT_REF.fullmatch(v) is not None


@dataclass(frozen=True, slots=True)
class InternalEvidencePointer:
    """An immutable *synthetic* document-manifest pointer, never source rights."""

    evidence_id: str
    document_ref: str
    version: int
    manifest_sha256: str
    purpose: str
    status: str = STATUS

    def __post_init__(self):
        if (self.evidence_id not in D1_EVIDENCE_IDS
                or not _reference(self.document_ref)
                or type(self.version) is not int or self.version < 1
                or not _digest(self.manifest_sha256)
                or self.purpose not in PURPOSES
                or self.status != STATUS):
            raise ValueError("invalid/unreviewed synthetic D1 evidence pointer")


def evidence_preflight(
    pointers: tuple[InternalEvidencePointer, ...] = (),
) -> dict:
    """Versioned internal preparation inventory, deliberately *never* a gate.

    All known evidence must be independently reviewed under an approved
    Business/Legal contract, with externally verifiable provenance. This
    offline projection has no approval or action methods by design.
    """
    if type(pointers) is not tuple:
        raise ValueError("immutable tuple evidence inventory required")
    keyed: dict[tuple[str, str], InternalEvidencePointer] = {}
    refs = set()
    for item in pointers:
        if not isinstance(item, InternalEvidencePointer):
            raise ValueError("evidence pointer not validated")
        key = item.evidence_id, item.purpose
        if key in keyed or item.document_ref in refs:
            raise ValueError("duplicate evidence identity / document reference")
        keyed[key] = item
        refs.add(item.document_ref)
    items = []
    for purpose in PURPOSES:
        for evidence_id in D1_EVIDENCE_IDS:
            item = keyed.get((evidence_id, purpose))
            items.append({
                "id": evidence_id,
                "purpose": purpose,
                "preparation_status": STATUS if item else "MISSING",
                "draft_document_ref": item.document_ref if item else None,
                "draft_version": item.version if item else None,
                # No digest or private source bytes in overview.
                "independent_review_verified": False,
                "usable_authority": False,
            })
    canonical = [
        (item.evidence_id, item.purpose, item.document_ref, item.version,
         item.manifest_sha256)
        for item in sorted(pointers, key=lambda x: (x.purpose, x.evidence_id))
    ]
    manifest = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return {
        "contract_version": CONTRACT_VERSION,
        "engine": "DOMESTIC",
        "snapshot_digest": sha256(manifest.encode("utf-8")).hexdigest(),
        "inventory_state": "INTERNAL_PREPARATION_NOT_ADMITTED",
        "provided_pointer_count": len(keyed),
        # Candidate inventory slots, NOT legally/operationally required
        # document counts. Business E01..E07 have no approved field schema.
        "candidate_review_slots": len(D1_EVIDENCE_IDS) * len(PURPOSES),
        "evidence_items": items,
        "source_rights_verified": False,
        "service_purpose_consent_verified": False,
        "training_purpose_rights_verified": False,
        "expert_qualification_verified": False,
        "scientific_quality_verified": False,
        "allow_real_household_data_ingest": False,
        "allow_household_plan_ai": False,
        "allow_ai_training": False,
        "allow_specialist_plan_approval": False,
        "allow_cross_engine_data_use": False,
        "allow_marketplace_publication": False,
        "business_gate_2_passed": False,
        "stage_or_production_admitted": False,
    }
