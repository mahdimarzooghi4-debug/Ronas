"""Cross-engine read-only decision blockers from exact DRAFT Business sources.

Not a live gate, verified evidence registry, rights clearance or admission.
"""
from __future__ import annotations

from hashlib import sha1
import json
from pathlib import Path

from .business_gate_evidence import (
    BusinessSourceSnapshotError, verify_pinned_business_sources,
)
from .financial_source_arithmetic import source_arithmetic

SOURCE_HEAD_AT_REVIEW = "9bcc0f41e492b6e886b09cddff436da922cb616f"
SNAPSHOT = "PINNED_DRAFT_NOT_LIVE"
PINNED_FILES = {
    "docs/business/core-three-gate-review-controls.json":
        "18c84dc049de40c613466d4b0908a331834fcf5a",
    "docs/business/official-source-rights-screening.json":
        "2ac1a87513ec22382572c19c6fb273dbc7ed2eac",
    "docs/business/75-operational-three-gate-decision-docket.md":
        "ab168f98cf56060a6e3abd279fc96490519b5a34",
    "docs/business/76-finance-source-arithmetic-and-evidence.md":
        "b993cf0b3dc107ed9f824da6d2d5e7e838fc0265",
    "docs/business/77-official-source-rights-screening.md":
        "b6885b54fa02c73c02f43393a4fe1c973b669d57",
}
DOMAINS = ("DOMESTIC", "EXPORT", "FINANCE")
SOURCE_IDS = {
    "DOMESTIC": ("DOM-AGROVOC", "DOM-FAO-PUBLICATIONS"),
    "EXPORT": ("EXP-FAOSTAT", "EXP-WORLD-BANK", "EXP-COMTRADE"),
    "FINANCE": (),
}
EVIDENCE_LABELS = {
    "real_audience_region_crop": "مخاطب، منطقه و محصول واقعی",
    "purpose_specific_consent_and_data_rights": "رضایت و حقوق داده هدف‌مند",
    "qualified_expert_and_science": "صلاحیت متخصص و شواهد علمی",
    "versioned_review_and_supervision": "بازبینی نسخه‌دار و نظارت",
    "seller_QC_and_publication_when_applicable": "کنترل مستقل کیفیت و اجازه عرضه",
    "owner_selected_real_product_destination": "محصول و مقصد منتخب مرجع مجاز",
    "source_date_unit_and_usage_rights": "حق استفاده، تاریخ و واحد مأخذ",
    "human_report_review_authority": "بازبین مسئول پژوهش",
    "separate_actual_contract_for_trade": "قرارداد مستقل معامله",
    "source_and_uses_with_classification": "منابع و مصارف طبقه‌بندی‌شده",
    "domestic_separate_PL_and_cashflow": "سود و جریان نقد Domestic",
    "each_export_contract_separate_PL_and_cashflow": "سود و جریان نقد هر قرارداد Export",
    "gross_net_and_double_count_review": "بررسی ناخالص/خالص و دوباره‌شماری",
    "rates_sources_and_dates": "منابع و تاریخ نرخ‌ها",
    "verified_receivables_payables_and_tax": "مطالبات و بدهی و مالیات",
    "unit_economics_and_approver": "اقتصاد واحد و مرجع تأیید",
}


def _read(root: Path, relative: str, expected: str) -> bytes:
    try:
        src = (root / relative).resolve(strict=True)
        if not src.is_relative_to(root) or not src.is_file():
            raise BusinessSourceSnapshotError("source outside local repository")
        raw = src.read_bytes()
        if len(raw) > 120000:
            raise BusinessSourceSnapshotError("oversize source")
        actual = sha1(
            b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
        ).hexdigest()
        if actual != expected:
            raise BusinessSourceSnapshotError("pinned source drift")
        return raw
    except OSError as exc:
        raise BusinessSourceSnapshotError("missing pinned source") from exc


def verify_decision_sources(*, root: Path | None = None) -> tuple[dict, dict]:
    base = (root if root is not None
            else Path(__file__).resolve().parents[2]).resolve()
    verify_pinned_business_sources(root=base)
    sources = {
        path: _read(base, path, digest)
        for path, digest in PINNED_FILES.items()
    }
    try:
        gates = json.loads(
            sources["docs/business/core-three-gate-review-controls.json"]
        )
        rights = json.loads(
            sources["docs/business/official-source-rights-screening.json"]
        )
    except (ValueError, UnicodeError) as exc:
        raise BusinessSourceSnapshotError("invalid pinned metadata") from exc
    if (gates.get("contract_version")
            != "ronas.business.three-gate-review-integrity.v1"
            or gates.get("snapshot_status") != "DRAFT_NOT_ADMITTED"
            or gates.get("source_record_only") is not True
            or any(gates.get(k) is not False for k in (
                "admission_authorized", "live_data_processing_authorized",
                "commercial_actions_authorized", "final_business_signatures_verified"))):
        raise BusinessSourceSnapshotError("unapproved gate asserted approved")
    dossiers = gates.get("dossiers")
    if not isinstance(dossiers, list) or len(dossiers) != 3:
        raise BusinessSourceSnapshotError("missing gate dossier")
    for d, domain, issue in zip(dossiers, DOMAINS, (2, 3, 4), strict=True):
        expected_source = (
            "docs/business/76-finance-source-arithmetic-and-evidence.md"
            if domain == "FINANCE" else
            "docs/business/75-operational-three-gate-decision-docket.md"
        )
        if (d.get("domain") != domain or d.get("issue") != issue
                or d.get("state") != "OPEN" or d.get("source") != expected_source
                or not isinstance(d.get("required_evidence"), list)
                or len(d["required_evidence"]) < 4
                or len(set(d["required_evidence"])) != len(d["required_evidence"])
                or any(k not in EVIDENCE_LABELS for k in d["required_evidence"])
                or not isinstance(d.get("prohibitions"), list)
                or not d["prohibitions"]):
            raise BusinessSourceSnapshotError("invalid draft evidence boundary")
    if (rights.get("contract_version") != "ronas.source-rights.screening.v1"
            or rights.get("overall_status")
            != "SOURCE_TERMS_SCREENED_NOT_DATASET_AUTHORIZED"
            or rights.get("all_gates_open") is not True
            or any(rights.get(k) is not False for k in (
                "legal_authority_assigned", "selected_actual_product_destination",
                "source_use_approved", "model_training_approved",
                "external_data_downloaded"))):
        raise BusinessSourceSnapshotError("unverified source marked authorized")
    candidates = rights.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 5:
        raise BusinessSourceSnapshotError("missing sources")
    expected = SOURCE_IDS["DOMESTIC"] + SOURCE_IDS["EXPORT"]
    if tuple(c.get("id") for c in candidates) != expected:
        raise BusinessSourceSnapshotError("source candidate changed")
    for c in candidates:
        domain = "DOMESTIC" if c["id"].startswith("DOM-") else "EXPORT"
        if (c.get("domain") != domain
                or c.get("rights_for_ronas_verified") is not False
                or c.get("training_rights_verified") is not False
                or c.get("source_data_ingested") is not False
                or c.get("actual_dataset_version") is not None
                or c.get("reviewed_by_authority") is not None
                or not isinstance(c.get("official_terms_urls"), list)
                or not c["official_terms_urls"]
                or not isinstance(c.get("review_flags"), list)
                or not c["review_flags"]):
            raise BusinessSourceSnapshotError("source screening is not accepted")
    return gates, rights


def readiness(domain: str, *, root: Path | None = None) -> dict:
    if domain not in DOMAINS:
        raise ValueError("unknown domain")
    gates, rights = verify_decision_sources(root=root)
    dossier = next(d for d in gates["dossiers"] if d["domain"] == domain)
    result = {
        "domain": domain, "gate_issue": dossier["issue"],
        "gate_status_at_source": "OPEN",
        "snapshot_state": SNAPSHOT,
        "business_head_at_review": SOURCE_HEAD_AT_REVIEW,
        "candidate_scopes_not_approved": list(dossier["scope_candidacies"]),
        "pending_evidence": [
            {"key": key, "label": EVIDENCE_LABELS[key], "verified": False}
            for key in dossier["required_evidence"]
        ],
        "prohibitions": list(dossier["prohibitions"]),
        "decision_authorized": False, "real_data_authorized": False,
        "operational_actions_enabled": False, "training_authorized": False,
        "sources_not_licensed": [
            {"id": c["id"], "name": c["source_name"],
             "official_terms_urls": list(c["official_terms_urls"]),
             "review_flags": list(c["review_flags"]),
             "rights_verified": False, "training_rights_verified": False}
            for c in rights["candidates"] if c["domain"] == domain
        ],
    }
    if domain == "FINANCE":
        result["source_arithmetic_not_budget"] = source_arithmetic(root=root)
    return result
