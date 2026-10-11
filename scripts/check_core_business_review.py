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
        "RON-DEC-015", "RON-DEC-021", "NOT ADMITTED",
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
    if (6760 + 750 != 7510
            or 18915 - 7510 != 11405):
        raise ReviewContractError("source arithmetic not reproducible")
    return {
        "status": "DRAFT_REVIEW_CONTRACT_CHECKED_NOT_GATE_PASSED",
        "gate_states_at_source": GATES | {},
        "all_gates_open_at_source": True,
        "business_admission_authorized": False,
        "real_data_processing_authorized": False,
        "payment_authorized": False,
        "technical_ci_is_not_human_approval": True,
        "source_sha256": {p: digest for p, (_, digest) in sources.items()},
        "manifest_sha256": manifest_sha,
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
