"""Conservative LOCAL/TEST Business evidence preflight, no admission decisions.

These read-model fields are *blocking diagnostics*, not legal checks.
A claimed digest, a byte-for-byte synthetic comparison, or a technical
human note can never establish origin, rights, reviewer qualification,
or a Business Gate PASS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BYTE_CHECK_NOT_PERFORMED = "NOT_CHECKED"
BYTE_CHECK_MATCH = "DEMO_BYTES_MATCH_CLAIM"
BYTE_CHECK_MISMATCH = "DEMO_BYTES_DIFFER_FROM_CLAIM"
BYTE_CHECK_NO_REFERENCE = "NO_REFERENCE"
BLOCKERS = (
    "ORIGIN_NOT_AUTHENTICATED",
    "SOURCE_RIGHTS_NOT_VERIFIED",
    "REVIEWER_QUALIFICATION_NOT_VERIFIED",
)


@dataclass(frozen=True, slots=True)
class EvidencePreflight:
    domain: str
    evidence_id: str
    technical_state: str
    review_revision: int
    bytes_check: str
    origin_state: Literal["NOT_AUTHENTICATED"] = "NOT_AUTHENTICATED"
    rights_state: Literal["NOT_VERIFIED"] = "NOT_VERIFIED"
    reviewer_qualification_state: Literal["NOT_VERIFIED"] = "NOT_VERIFIED"
    evidence_verified: Literal[False] = False
    admission_allowed: Literal[False] = False
    business_gate_passed: Literal[False] = False

    def public_view(self) -> dict:
        checks = list(BLOCKERS)
        if self.bytes_check != BYTE_CHECK_MATCH:
            checks.insert(0, "EVIDENCE_BYTES_NOT_ATTESTED")
        return {
            "domain": self.domain, "evidence_id": self.evidence_id,
            "technical_state": self.technical_state,
            "review_revision": self.review_revision,
            "bytes_check": self.bytes_check,
            "origin_state": self.origin_state,
            "rights_state": self.rights_state,
            "reviewer_qualification_state": self.reviewer_qualification_state,
            "evidence_verified": self.evidence_verified,
            "admission_allowed": self.admission_allowed,
            "business_gate_passed": self.business_gate_passed,
            "blockers": checks,
        }


def preflight_for_status(item: dict, *, bytes_check: str = BYTE_CHECK_NOT_PERFORMED) -> dict:
    if bytes_check not in (
        BYTE_CHECK_NOT_PERFORMED, BYTE_CHECK_MATCH,
        BYTE_CHECK_MISMATCH, BYTE_CHECK_NO_REFERENCE,
    ):
        raise ValueError("unsupported synthetic byte inspection state")
    if item.get("technical_state") not in (
        "NO_REFERENCE", "REFERENCE_RECORDED", "HUMAN_NOTE_RECORDED",
    ):
        raise ValueError("unsupported reference review state")
    if (type(item.get("review_revision")) is not int
            or item["review_revision"] not in (0, 1, 2)
            or (item["technical_state"], item["review_revision"]) not in (
                ("NO_REFERENCE", 0),
                ("REFERENCE_RECORDED", 1),
                ("HUMAN_NOTE_RECORDED", 2),
            )):
        raise ValueError("invalid technical stage/revision")
    return EvidencePreflight(
        domain=item["domain"], evidence_id=item["evidence_id"],
        technical_state=item["technical_state"],
        review_revision=item["review_revision"], bytes_check=bytes_check,
    ).public_view()
