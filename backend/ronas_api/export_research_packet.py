"""Deterministic, citation-reference-only Export research packet (LOCAL/TEST)."""
from __future__ import annotations

from hashlib import sha256
import json


VERSION = "ronas.export.local-test.research-packet.v1"


class ExportResearchPacketConflict(ValueError):
    """The Export research workspace changed while the packet was assembled."""


class ExportResearchPacketIntegrityError(RuntimeError):
    """Workspace material cannot safely be projected into an Export packet."""


def _context(workspace: dict) -> dict:
    if (not isinstance(workspace, dict) or workspace.get("engine") != "EXPORT"
            or workspace.get("case_status") != "DRAFT_ONLY"
            or workspace.get("source") != "SYNTHETIC_ONLY"
            or workspace.get("source_rights_verified") is not False
            or workspace.get("research_report_approved") is not False
            or workspace.get("buyer_verified") is not False
            or workspace.get("contracted") is not False
            or workspace.get("real_data") is not False
            or workspace.get("business_actions_enabled") is not False):
        raise ExportResearchPacketIntegrityError("Export workspace is outside packet scope")
    ref, case_version = workspace.get("ref"), workspace.get("case_version")
    question = workspace.get("local_test_draft_question")
    evidence = workspace.get("local_test_evidence_references")
    if (not isinstance(ref, str) or not ref.startswith("DEMO-E-")
            or type(case_version) is not int or case_version < 1
            or question is not None and not isinstance(question, dict)
            or not isinstance(evidence, list)):
        raise ExportResearchPacketIntegrityError("Export workspace context is malformed")
    return {
        "ref": ref, "case_version": case_version,
        "question": question,
        "evidence": evidence,
    }


def _fingerprint(context: dict) -> str:
    return sha256(json.dumps(
        context, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("ascii")).hexdigest()


def _demo_ref(value: object, prefix: str) -> bool:
    return (isinstance(value, str) and value.startswith(prefix)
            and len(value) <= 160 and value.isascii())


def _digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def build_export_research_packet(workspace_before: dict, findings: list,
                                 workspace_after: dict) -> dict:
    """Bind a packet to one stable case/question/evidence snapshot.

    The packet contains only opaque source references and analyst DEMO notes;
    it never copies connector bytes or infers market conclusions.
    """
    before, after = _context(workspace_before), _context(workspace_after)
    if _fingerprint(before) != _fingerprint(after):
        raise ExportResearchPacketConflict("Export context changed during packet assembly")
    if not isinstance(findings, list):
        raise ExportResearchPacketIntegrityError("Export finding collection is malformed")
    question = before["question"]
    if question is not None:
        if (question.get("question_state") != "UNVERIFIED_LOCAL_TEST_DRAFT"
                or type(question.get("question_revision")) is not int
                or question.get("source_rights_verified") is not False
                or question.get("research_report_approved") is not False
                or not _demo_ref(question.get("source_ref"), "DEMO-SOURCE-")
                or not _demo_ref(question.get("product_ref"), "DEMO-PRODUCT-")
                or not _demo_ref(question.get("destination_ref"), "DEMO-DEST-")):
            raise ExportResearchPacketIntegrityError("Export question is outside packet scope")
        question_view = {
            "question_revision": question["question_revision"],
            "question_state": question["question_state"],
            "source_ref": question.get("source_ref"),
            "product_ref": question.get("product_ref"),
            "destination_ref": question.get("destination_ref"),
        }
        current_question = question["question_revision"]
    else:
        question_view = None
        current_question = None

    evidence_view = []
    for item in before["evidence"]:
        if (not isinstance(item, dict)
                or item.get("engine") != "EXPORT"
                or item.get("source_rights_verified") is not False
                or item.get("real_data") is not False
                or type(item.get("question_revision")) is not int
                or type(item.get("evidence_revision")) is not int
                or item.get("question_binding") not in {"CURRENT", "HISTORICAL"}
                or not _demo_ref(item.get("source_ref"), "DEMO-SOURCE-")
                or not _demo_ref(item.get("evidence_ref"), "DEMO-EVIDENCE-")
                or not _demo_ref(item.get("connector_ref"), "DEMO-CONNECTOR-")
                or not _digest(item.get("source_snapshot_digest"))):
            raise ExportResearchPacketIntegrityError("Export evidence reference is malformed")
        evidence_view.append({
            "question_revision": item.get("question_revision"),
            "evidence_revision": item.get("evidence_revision"),
            "source_ref": item.get("source_ref"),
            "evidence_ref": item.get("evidence_ref"),
            "connector_ref": item.get("connector_ref"),
            "source_snapshot_digest": item.get("source_snapshot_digest"),
            "question_binding": item.get("question_binding"),
        })

    finding_view = []
    for item in findings:
        if (not isinstance(item, dict) or item.get("draft_only") is not True
                or item.get("report_approved") is not False
                or not isinstance(item.get("note"), str)
                or not item["note"].startswith("DEMO:")
                or type(item.get("question_revision")) is not int
                or type(item.get("evidence_revision")) is not int
                or type(item.get("revision")) is not int
                or item.get("question_binding") not in {"CURRENT", "HISTORICAL"}
                or item.get("evidence_binding") not in {"CURRENT", "HISTORICAL"}
                or not _demo_ref(item.get("source_ref"), "DEMO-SOURCE-")
                or not _demo_ref(item.get("evidence_ref"), "DEMO-EVIDENCE-")
                or not _demo_ref(item.get("connector_ref"), "DEMO-CONNECTOR-")
                or not _digest(item.get("source_snapshot_digest"))):
            raise ExportResearchPacketIntegrityError("Export finding is outside packet scope")
        finding_view.append({
            "question_revision": item.get("question_revision"),
            "evidence_revision": item.get("evidence_revision"),
            "revision": item.get("revision"),
            "evidence_ref": item.get("evidence_ref"),
            "source_ref": item.get("source_ref"),
            "connector_ref": item.get("connector_ref"),
            "source_snapshot_digest": item.get("source_snapshot_digest"),
            "question_binding": item.get("question_binding"),
            "evidence_binding": item.get("evidence_binding"),
            "note": item["note"],
        })

    packet = {
        "contract_version": VERSION,
        "engine": "EXPORT",
        "case_ref": before["ref"],
        "case_version": before["case_version"],
        "packet_state": "UNVERIFIED_LOCAL_TEST_DRAFT",
        "question": question_view,
        "evidence_references": evidence_view,
        "findings": finding_view,
        "limitations": {
            "source_rights_verified": False,
            "source_data_ingested": False,
            "research_report_approved": False,
            "buyer_verified": False,
            "contracted": False,
            "publication_enabled": False,
            "commercial_actions_enabled": False,
        },
        "draft_only": True,
        "report_approved": False,
    }
    packet["packet_digest"] = _fingerprint(packet)
    return packet
