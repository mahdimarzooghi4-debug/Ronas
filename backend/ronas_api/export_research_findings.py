"""Append-only, DEMO-only Export finding notes bound to a question and source ref.

Notes are not verified market facts, a published report, or trade advice.
"""
from __future__ import annotations

from hashlib import sha256
import json

from .scoped_drafts import _synthetic_ref

VERSION = "ronas.export.local-test.research-finding.v1"
RECORDED = "EXPORT_RESEARCH_FINDING_RECORDED"


class ExportResearchFindingConflict(ValueError):
    """The question, evidence, or finding revision changed."""


def finding_binding(*, action_id: str, ref: str, case_version: int,
                    question_revision: int, evidence_revision: int,
                    revision: int, actor_digest: str, evidence_ref: str,
                    note_digest: str, previous_digest: str) -> dict:
    if (not _synthetic_ref(action_id) or not _synthetic_ref(ref)
            or type(case_version) is not int or case_version < 1
            or type(question_revision) is not int or question_revision < 1
            or type(evidence_revision) is not int or evidence_revision < 1
            or type(revision) is not int or revision < 1
            or not _digest(actor_digest) or not _synthetic_ref(evidence_ref)
            or not evidence_ref.startswith("DEMO-EVIDENCE-")
            or not _digest(note_digest) or not _digest(previous_digest)):
        raise ValueError("invalid bounded Export finding")
    return {
        "contract": VERSION, "engine": "EXPORT", "ref": ref,
        "case_version": case_version, "question_revision": question_revision,
        "evidence_revision": evidence_revision, "revision": revision,
        "action_id": action_id, "actor_digest": actor_digest,
        "evidence_ref": evidence_ref, "note_digest": note_digest,
        "previous_digest": previous_digest,
    }


def finding_digest(binding: dict) -> str:
    return sha256(json.dumps(
        binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")).hexdigest()


def _digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))
