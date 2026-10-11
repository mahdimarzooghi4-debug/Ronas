"""Ronas Business PR #1 draft integrity + acceptance-boundary check.

Offline source-doc controls, NEVER a legal decision, live evidence attestation,
Business gate engine, financial model or real product approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

MANIFEST = "docs/business/core-three-gate-review-controls.json"
SOURCE_SCREEN_REGISTRY = "docs/business/official-source-rights-screening.json"
SOURCE_SCREEN_DOC = "docs/business/77-official-source-rights-screening.md"
EXPECTED_SOURCE_URLS = {
    "DOM-AGROVOC": "https://aims.fao.org/standards/agrovoc/faq",
    "DOM-FAO-PUBLICATIONS": "https://www.fao.org/publications/about-fao-publishing/permissions/",
    "EXP-FAOSTAT": "https://www.fao.org/contact-us/terms/db-terms-of-use/en",
    "EXP-WORLD-BANK": "https://datacatalog.worldbank.org/public-licenses",
    "EXP-COMTRADE": "https://uncomtrade.org/docs/policy-on-comtrade-data-use/",
}
REQUIRED_SOURCE_FLAGS = {
    "DOM-AGROVOC": {"OFFICIAL_PAGES_LICENSE_VERSION_DIFFER",
                    "LANGUAGE_AND_THIRD_PARTY_OWNERSHIP",
                    "THESAURUS_NOT_SCIENTIFIC_PLAN_SOURCE"},
    "DOM-FAO-PUBLICATIONS": {"NONCOMMERCIAL_DEFAULT_DOES_NOT_AUTHORIZE_RONAS_COMMERCIAL_REUSE",
                             "THIRD_PARTY_CONTENT_CHECK"},
    "EXP-FAOSTAT": {"DATABASE_ADDITIONAL_RESTRICTIONS",
                     "NO_FAO_COMMERCIAL_PROMOTION_OR_ENDORSEMENT",
                     "DATASET_METADATA_AND_THIRD_PARTY_EXCEPTIONS"},
    "EXP-WORLD-BANK": {"DATASET_BY_DATASET_LICENSE",
                       "THIRD_PARTY_RESTRICTIONS"},
    "EXP-COMTRADE": {"INTERNAL_USE_NOT_PUBLIC_REDISTRIBUTION",
                     "RE-DISSEMINATION_EXCEPTION_NOT_AUTOMATIC",
                     "COMMERCIAL_USE_REQUIRES_SPECIFIC_TERMS_REVIEW"},
}
BUSINESS_SOURCES = (
    "docs/business/03-financial-assumptions-and-gaps.md",
    "docs/business/55-finance-macro-business-decision-package.md",
    "docs/business/70-core-domestic-operational-scope-and-business-acceptance.md",
    "docs/business/71-core-export-operational-contract-and-readiness.md",
    "docs/business/74-operational-build-readiness-audit-and-first-thin-slices.md",
    "docs/business/75-operational-three-gate-decision-docket.md",
    "docs/business/76-finance-source-arithmetic-and-evidence.md",
)
GATES = {"DOMESTIC": 2, "EXPORT": 3, "FINANCE": 4}
DECISION_ANCHORS = {
    "DOMESTIC": (
        "CORE-D1-A", "CORE-D1-B", "CORE-D2",
        "PRODUCER_CONTROLS_FINAL_PRICE",
        "NO_PUBLIC_OFFER_WITHOUT_PRODUCER_AND_QC",
    ),
    "EXPORT": (
        "CORE-E0-A", "NO_AUTO_TRANSFER_DOMESTIC_DATA",
        "NO_SOURCE_USE_WITHOUT_RIGHTS",
    ),
    "FINANCE": (
        "FIN-001", "FIN-002", "FIN-003", "FIN-004",
        "FIN-005", "FIN-006", "FIN-007",
        "NO_PROFIT_EQUALS_CASH",
    ),
}
NO_APPROVAL_FLAGS = (
    "admission_authorized",
    "live_data_processing_authorized",
    "commercial_actions_authorized",
    "final_business_signatures_verified",
)


class ReviewContractError(RuntimeError):
    """Required source/contract is absent, corrupted or misleading."""


def _read(root: Path, relative_path: str) -> tuple[str, str]:
    if (not relative_path.startswith("docs/business/")
            or ".." in Path(relative_path).parts):
        raise ReviewContractError("unexpected source location")
    try:
        p = (root / relative_path).resolve(strict=True)
        if not p.is_relative_to(root) or not p.is_file() or p.stat().st_size > 120000:
            raise ReviewContractError("invalid source file")
        content = p.read_bytes()
        return content.decode("utf-8"), hashlib.sha256(content).hexdigest()
    except (OSError, UnicodeError) as exc:
        raise ReviewContractError("missing or invalid source") from exc


def validate_business_review(root: Path | None = None) -> dict:
    base = (root if root is not None
            else Path(__file__).resolve().parents[1]).resolve()
    body, manifest_sha = _read(base, MANIFEST)
    try:
        doc = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ReviewContractError("invalid review controls") from exc
    if (doc.get("contract_version")
            != "ronas.business.three-gate-review-integrity.v1"
            or doc.get("snapshot_status") != "DRAFT_NOT_ADMITTED"
            or doc.get("source_record_only") is not True
            or any(doc.get(key) is not False for key in NO_APPROVAL_FLAGS)):
        raise ReviewContractError("attempted Business admission through a draft")
    dossiers = doc.get("dossiers")
    if (not isinstance(dossiers, list) or len(dossiers) != 3
            or {x.get("domain") for x in dossiers if isinstance(x, dict)}
            != set(GATES)):
        raise ReviewContractError("three independent gates required")
    sources = {p: _read(base, p) for p in BUSINESS_SOURCES}
    domestic = sources[BUSINESS_SOURCES[2]][0]
    exporting = sources[BUSINESS_SOURCES[3]][0]
    financing = sources[BUSINESS_SOURCES[0]][0]
    # All source bytes, not just one FIN-002 paragraph, must be the exact
    # already-reviewed Git blob. Future changes require explicit re-review.
    finance_raw = financing.encode("utf-8")
    finance_git_sha = hashlib.sha1(
        b"blob " + str(len(finance_raw)).encode("ascii") + b"\0"
        + finance_raw
    ).hexdigest()
    if finance_git_sha != "93b1c5073917fc095ae341394a90b09d7c02fd1f":
        raise ReviewContractError("finance source file version changed")
    packet = sources[BUSINESS_SOURCES[5]][0]
    finance_packet = sources[BUSINESS_SOURCES[6]][0]
    if not ("DRAFT" in domestic[:500] and "NOT APPROVED" in domestic[:500]
            and "DRAFT" in exporting[:500] and "NO EXPORT TRADE" in exporting[:500]
            and "DRAFT DECISION REQUEST" in packet[:500]
            and "NOT A CORRECTED BUDGET" in finance_packet[:300]
            and "OPEN" in packet and "OPEN" in finance_packet):
        raise ReviewContractError("Business candidate/approval boundary changed")
    for d in dossiers:
        domain = d["domain"]
        if (d.get("issue") != GATES[domain] or d.get("state") != "OPEN"
                or not isinstance(d.get("required_evidence"), list)
                or not d["required_evidence"]
                or any(not isinstance(v, str) or not v
                       for v in d["required_evidence"])
                or not isinstance(d.get("prohibitions"), list)
                or not d["prohibitions"]
                or len(set(d["prohibitions"])) != len(d["prohibitions"])
                or d.get("source") not in sources):
            raise ReviewContractError("gate cannot be silently admitted")
        if d["source"] != (BUSINESS_SOURCES[6] if domain == "FINANCE"
                             else BUSINESS_SOURCES[5]):
            raise ReviewContractError("wrong source boundary for domain")
        if any(anchor not in (packet + finance_packet + json.dumps(d))
               for anchor in DECISION_ANCHORS[domain]):
            raise ReviewContractError("missing previously approved boundary")
    if (len({d["source"] for d in dossiers}) != 2
            or len({tuple(d["prohibitions"]) for d in dossiers}) != 3):
        raise ReviewContractError("contract boundaries must remain independent")
    for assertion in (
        "RON-DEC-009", "RON-DEC-010", "RON-DEC-011",
        "RON-DEC-015", "RON-DEC-015..021", "NOT ADMITTED",
    ):
        if assertion not in domestic:
            raise ReviewContractError("approved Domestic invariant/source missing")
    for assertion in ("RON-DEC-003", "E-03", "E-04", "NO EXPORT TRADE"):
        if assertion not in exporting:
            raise ReviewContractError("Export contract/source missing")
    for assertion in ("RON-DEC-024", "FIN-001", "FIN-007"):
        if assertion not in (financing + sources[BUSINESS_SOURCES[1]][0]):
            raise ReviewContractError("Finance directional source missing")
    # Only SOURCE mathematics; this does not infer the accounting classification.
    source_numbers = ("۱۸٬۹۱۵", "۶٬۷۶۰", "۷۵۰", "۷٬۵۱۰", "۱۱٬۴۰۵")
    fin002 = financing.split("**FIN-002 — تعریف سرمایه اولیه.**")
    if len(fin002) != 2 or not all(x in fin002[1].split("\n\n", 1)[0]
                                     for x in source_numbers):
        raise ReviewContractError("FIN-002 source figures were altered")
    if not all(x in finance_packet for x in source_numbers):
        raise ReviewContractError("FIN-002 review figures diverged from source")
    if not re.search(
        r"^\|\s*تفاوت سرمایه اعلامی و جمع ردیف‌ها\s*\|\s*\*\*۱۱٬۴۰۵\*\*\s*\|",
        finance_packet, re.MULTILINE,
    ):
        raise ReviewContractError("FIN-002 review difference row changed")
    if (6760 + 750 != 7510
            or 18915 - 7510 != 11405):
        raise ReviewContractError("source arithmetic not reproducible")
    src_body, src_hash = _read(base, SOURCE_SCREEN_REGISTRY)
    doc_body, doc_hash = _read(base, SOURCE_SCREEN_DOC)
    try:
        screened = json.loads(src_body)
    except json.JSONDecodeError as exc:
        raise ReviewContractError("malformed source screening") from exc
    if (screened.get("contract_version") != "ronas.source-rights.screening.v1"
            or screened.get("overall_status")
            != "SOURCE_TERMS_SCREENED_NOT_DATASET_AUTHORIZED"
            or screened.get("checked_on") != "2026-10-11"
            or screened.get("all_gates_open") is not True
            or (screened.get("domestic_gate"), screened.get("export_gate"),
                screened.get("finance_gate")) != (2, 3, 4)
            or any(screened.get(k) is not False for k in (
                "legal_authority_assigned", "selected_actual_product_destination",
                "source_use_approved", "model_training_approved",
                "external_data_downloaded"))):
        raise ReviewContractError("source rights cannot be approved by a screen")
    sources_checked = screened.get("candidates")
    if (not isinstance(sources_checked, list) or len(sources_checked) != 5
            or {s.get("id") for s in sources_checked if isinstance(s, dict)}
            != set(EXPECTED_SOURCE_URLS)):
        raise ReviewContractError("screening requires five distinct candidates")
    count = {"DOMESTIC": 0, "EXPORT": 0}
    for s in sources_checked:
        ident = s["id"]
        expected_domain = "DOMESTIC" if ident.startswith("DOM-") else "EXPORT"
        count[expected_domain] += 1
        urls = s.get("official_terms_urls")
        flags = s.get("review_flags")
        if (s.get("domain") != expected_domain
                or not isinstance(urls, list)
                or EXPECTED_SOURCE_URLS[ident] not in urls
                or not all(isinstance(url, str) and url.startswith(
                    ("https://www.fao.org/", "https://aims.fao.org/",
                     "https://datacatalog.worldbank.org/",
                     "https://www.worldbank.org/",
                     "https://uncomtrade.org/",
                     "https://comtradeplus.un.org/")
                ) for url in urls)
                or not isinstance(flags, list)
                or not REQUIRED_SOURCE_FLAGS[ident].issubset(set(flags))
                or any(s.get(f) is not False for f in (
                    "rights_for_ronas_verified", "training_rights_verified",
                    "source_data_ingested"))
                or s.get("actual_dataset_version") is not None
                or s.get("reviewed_by_authority") is not None
                or not s.get("rights_observation")
                or not s.get("proposed_usage")
                or not isinstance(s.get("source_name"), str)
                or not s.get("source_name")):
            raise ReviewContractError("source screen is not rights authorization")
    if count != {"DOMESTIC": 2, "EXPORT": 3}:
        raise ReviewContractError("source rights engine boundary changed")
    for official in EXPECTED_SOURCE_URLS.values():
        if official not in doc_body:
            raise ReviewContractError("source claims not traceable to official terms")
    if ("NO INGESTION" not in doc_body[:450]
            or "NO LEGAL SIGNOFF" not in doc_body[:450]):
        raise ReviewContractError("screening is no longer explicitly unapproved")
    return {
        "status": "DRAFT_REVIEW_CONTRACT_CHECKED_NOT_GATE_PASSED",
        "gate_states_at_source": {name: "OPEN" for name in GATES},
        "all_gates_open_at_source": True,
        "business_admission_authorized": False,
        "real_data_processing_authorized": False,
        "payment_authorized": False,
        "technical_ci_is_not_human_approval": True,
        "source_sha256": {p: digest for p, (_, digest) in sources.items()},
        "manifest_sha256": manifest_sha,
        "source_screening": {
            "number_of_candidates": len(sources_checked),
            "domestic_sources": count["DOMESTIC"],
            "export_sources": count["EXPORT"],
            "authorized_for_ingestion": False,
            "authorized_for_training": False,
            "screened_sources_sha256": src_hash,
            "rights_document_sha256": doc_hash,
        },
        "financial_source_arithmetic": {
            "unit": "million_toman",
            "quoted_initial_capital": 18915,
            "quoted_equipment_plus_preoperating": 7510,
            "arithmetic_difference": 11405,
            "classification_authorized": False,
        },
    }


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("--root", type=Path)
    args.add_argument("--json", action="store_true")
    parsed = args.parse_args()
    try:
        result = validate_business_review(parsed.root)
    except ReviewContractError as exc:
        args.exit(1, f"Business DRAFT consistency failure: {exc}\n")
    if parsed.json:
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
    else:
        print(result["status"])
