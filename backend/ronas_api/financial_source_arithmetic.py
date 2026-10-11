"""Read-only reproduction of explicitly quoted FIN-002 source arithmetic.

This is NOT a capital budget, cash-flow engine, authoritative financial
record, actual price, approved Finance model, or settlement calculation.
"""
from __future__ import annotations

from hashlib import sha1
from pathlib import Path

from .business_gate_evidence import BusinessSourceSnapshotError

SOURCE_PATH = "docs/business/03-financial-assumptions-and-gaps.md"
SOURCE_BLOB_SHA = "93b1c5073917fc095ae341394a90b09d7c02fd1f"
UNIT = "million_toman"
# Exact numbers transcribed from the source review's FIN-002 paragraph.
# These are *source claims*, not verified financial amounts.
REPORTED_CAPITAL = 18915
EQUIPMENT_SOURCE = 6760
PRE_OPERATING_SOURCE = 750
YEAR_ONE_OPERATING_SOURCE = 11405


def source_arithmetic(*, root: Path | None = None) -> dict:
    base = (root if root is not None
            else Path(__file__).resolve().parents[2]).resolve()
    try:
        source = (base / SOURCE_PATH).resolve(strict=True)
        if not source.is_relative_to(base) or not source.is_file():
            raise BusinessSourceSnapshotError("untrusted finance source")
        raw = source.read_bytes()
        if len(raw) > 80_000:
            raise BusinessSourceSnapshotError("unexpected finance source size")
        digest = sha1(
            b"blob " + str(len(raw)).encode("ascii") + b"\\0" + raw
        ).hexdigest()
        if digest != SOURCE_BLOB_SHA:
            raise BusinessSourceSnapshotError("finance source drift")
        body = raw.decode("utf-8")
        marker = "**FIN-002 — تعریف سرمایه اولیه.**"
        section = body.split(marker)
        if len(section) != 2:
            raise BusinessSourceSnapshotError("finance source section missing")
        block = section[1].split("\n\n", 1)[0]
        if not all(number in block for number in (
            "۱۸٬۹۱۵", "۶٬۷۶۰", "۷۵۰", "۷٬۵۱۰", "۱۱٬۴۰۵",
        )):
            raise BusinessSourceSnapshotError("finance amounts not grounded")
    except (OSError, UnicodeError, ValueError) as exc:
        raise BusinessSourceSnapshotError("finance source unavailable") from exc

    components = EQUIPMENT_SOURCE + PRE_OPERATING_SOURCE
    difference = REPORTED_CAPITAL - components
    if components != 7510 or difference != YEAR_ONE_OPERATING_SOURCE:
        raise BusinessSourceSnapshotError("finance source arithmetic mismatch")
    return {
        "contract_version": "ronas.finance.source-arithmetic.v0",
        "source_path": SOURCE_PATH,
        "source_blob_sha": SOURCE_BLOB_SHA,
        "source_state": "PINNED_DRAFT_SOURCE_NOT_LIVE",
        "unit": UNIT,
        "reported_initial_capital": REPORTED_CAPITAL,
        "reported_equipment": EQUIPMENT_SOURCE,
        "reported_pre_operating": PRE_OPERATING_SOURCE,
        "arithmetic_component_sum": components,
        "arithmetic_unexplained_difference": difference,
        "reported_year_one_operating_cost": YEAR_ONE_OPERATING_SOURCE,
        "difference_equals_year_one_operating_source": True,
        "classification_resolved": False,
        "corrected_budget_approved": False,
        "operating_cashflow_verified": False,
        "payments_enabled": False,
        "finance_gate_passed": False,
        "finance_gate_at_source": "OPEN",
        "findings": (
            "FIN-001/003/004/005/006/007 remain unresolved",
            "Numerical coincidence does not authorize capitalization, "
            "double-counting conclusions or correction of the source model",
        ),
    }
