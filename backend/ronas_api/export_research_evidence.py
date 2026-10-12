"""Opaque Export source-reference capture bound to a DEMO question revision.

No raw source bytes, citations, licensing claims, market findings, or reports
are accepted here. The connector-supplied fingerprint is an opaque digest.
"""
from __future__ import annotations

from hashlib import sha256
import json

from .scoped_drafts import _synthetic_ref

VERSION = "ronas.export.local-test.evidence-reference.v0"
RECORDED = "EXPORT_EVIDENCE_REFERENCE_RECORDED"


class ExportEvidenceReferenceConflict(ValueError):
    """Optimistic evidence revision or immutable command conflict."""


def valid_evidence_refs(evidence_ref: str, connector_ref: str) -> bool:
    return (
        _synthetic_ref(evidence_ref)
        and evidence_ref.startswith("DEMO-EVIDENCE-")
        and _synthetic_ref(connector_ref)
        and connector_ref.startswith("DEMO-CONNECTOR-")
    )


def valid_snapshot_digest(value: str) -> bool:
    return (
        isinstance(value, str) and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def evidence_binding(*, action_id: str, ref: str, case_version: int,
                     question_revision: int, revision: int, actor_digest: str,
                     source_ref: str, evidence_ref: str, connector_ref: str,
                     snapshot_digest: str) -> dict:
    if (not _synthetic_ref(action_id) or not _synthetic_ref(ref)
            or type(case_version) is not int or case_version < 1
            or type(question_revision) is not int or question_revision < 1
            or type(revision) is not int or revision < 1
            or type(actor_digest) is not str or len(actor_digest) != 64
            or any(c not in "0123456789abcdef" for c in actor_digest)
            or not _synthetic_ref(source_ref)
            or not valid_evidence_refs(evidence_ref, connector_ref)
            or not valid_snapshot_digest(snapshot_digest)):
        raise ValueError("invalid bounded DEMO Export evidence reference")
    return {
        "contract": VERSION, "engine": "EXPORT", "ref": ref,
        "case_version": case_version,
        "question_revision": question_revision, "revision": revision,
        "action_id": action_id, "actor_digest": actor_digest,
        "source_ref": source_ref, "evidence_ref": evidence_ref,
        "connector_ref": connector_ref,
        "source_snapshot_digest": snapshot_digest,
    }


def evidence_digest(binding: dict) -> str:
    return sha256(json.dumps(
        binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")).hexdigest()


def evidence_preview(*, ref: str, case_version: int, question_revision: int,
                     revision: int, source_ref: str, evidence_ref: str,
                     connector_ref: str, snapshot_digest: str,
                     current_question: bool) -> dict:
    return {
        "contract_version": VERSION, "engine": "EXPORT",
        "case_ref": ref, "case_version": case_version,
        "question_revision": question_revision,
        "evidence_revision": revision, "source_ref": source_ref,
        "evidence_ref": evidence_ref, "connector_ref": connector_ref,
        "source_snapshot_digest": snapshot_digest,
        "question_binding": "CURRENT" if current_question else "HISTORICAL",
        "source_rights_verified": False, "source_data_ingested": False,
        "research_findings": None, "research_report_approved": False,
        "buyer_verified": False, "contracted": False, "real_data": False,
    }
