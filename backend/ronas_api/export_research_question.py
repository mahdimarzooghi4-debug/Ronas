"""Human-authored DEMO export research-question reference contract (LOCAL/TEST).

Reference tokens are NOT real country/product/market data, evidence, source
rights, a completed research report, or trade approval.
"""
from __future__ import annotations

from hashlib import sha256
import json

from .scoped_drafts import _synthetic_ref

VERSION = "ronas.export.local-test.research-question.v0"
RECORDED = "EXPORT_RESEARCH_QUESTION_RECORDED"


class ExportResearchQuestionConflict(ValueError):
    """Optimistic draft question revision, action or case version mismatch."""


def valid_question_refs(product_ref: str, destination_ref: str) -> bool:
    return (
        _synthetic_ref(product_ref)
        and product_ref.startswith("DEMO-PRODUCT-")
        and _synthetic_ref(destination_ref)
        and destination_ref.startswith("DEMO-DEST-")
    )


def question_binding(*, action_id: str, ref: str, case_version: int,
                     revision: int, actor_digest: str, source_ref: str,
                     product_ref: str, destination_ref: str) -> dict:
    if (not _synthetic_ref(action_id) or not _synthetic_ref(ref)
            or type(case_version) is not int or case_version < 1
            or type(revision) is not int or revision < 1
            or type(actor_digest) is not str or len(actor_digest) != 64
            or any(c not in "0123456789abcdef" for c in actor_digest)
            or not _synthetic_ref(source_ref)
            or not valid_question_refs(product_ref, destination_ref)):
        raise ValueError("invalid bounded DEMO export question")
    return {
        "contract": VERSION, "engine": "EXPORT", "ref": ref,
        "case_version": case_version, "revision": revision,
        "action_id": action_id, "actor_digest": actor_digest,
        "source_ref": source_ref, "product_ref": product_ref,
        "destination_ref": destination_ref,
    }


def question_digest(binding: dict) -> str:
    return sha256(json.dumps(
        binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")).hexdigest()


def question_preview(*, ref: str, case_version: int, revision: int,
                     source_ref: str, product_ref: str,
                     destination_ref: str) -> dict:
    return {
        "contract_version": VERSION,
        "engine": "EXPORT", "case_ref": ref, "case_version": case_version,
        "question_revision": revision,
        "question_state": "UNVERIFIED_LOCAL_TEST_DRAFT",
        "source_ref": source_ref,
        "product_ref": product_ref,
        "destination_ref": destination_ref,
        "research_findings": None, "hs_code": None,
        "source_rights_verified": False,
        "research_report_approved": False,
        "buyer_verified": False, "contracted": False,
        "commercial_actions_enabled": False, "real_data": False,
    }
