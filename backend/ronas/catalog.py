"""Immutable discovery-only manifest for the two independent Ronas engines.

All capability names are derived from docs/business/01-domestic-engine.md
and docs/business/02-export-engine.md. They are NOT implemented flows.
"""

from dataclasses import dataclass
from typing import Final, Literal

DesignStatus = Literal["DESIGN_ONLY"]


@dataclass(frozen=True, slots=True)
class Capability:
    code: str
    title_fa: str
    source_ref: str
    status: DesignStatus = "DESIGN_ONLY"


@dataclass(frozen=True, slots=True)
class Engine:
    key: str
    title_fa: str
    source_ref: str
    capabilities: tuple[Capability, ...]
    business_gate: Literal["OPEN"] = "OPEN"


def _capability(code: str, title: str, source: str) -> Capability:
    return Capability(code=code, title_fa=title, source_ref=source)


_DOMESTIC_SOURCE: Final = "docs/business/01-domestic-engine.md"
_EXPORT_SOURCE: Final = "docs/business/02-export-engine.md"

DOMESTIC: Final = Engine(
    key="domestic",
    title_fa="موتور بازار داخلی",
    source_ref=_DOMESTIC_SOURCE,
    capabilities=(
        _capability("D-01", "عضویت خانوار", _DOMESTIC_SOURCE),
        _capability("D-02", "ارزیابی فضای کشت", _DOMESTIC_SOURCE),
        _capability("D-03", "پیشنهاد برنامه کشت", _DOMESTIC_SOURCE),
        _capability("D-04", "تجهیزات و فروشندگان", _DOMESTIC_SOURCE),
        _capability("D-05", "پایش فعالیت کشت", _DOMESTIC_SOURCE),
        _capability("D-06", "ثبت برداشت و مازاد", _DOMESTIC_SOURCE),
        _capability("D-07", "بازار محلی", _DOMESTIC_SOURCE),
        _capability("D-08", "تحویل محلی", _DOMESTIC_SOURCE),
        _capability("D-09", "رسیدگی به اختلاف", _DOMESTIC_SOURCE),
        _capability("D-10", "مالی و تسویه داخلی", _DOMESTIC_SOURCE),
    ),
)

EXPORT: Final = Engine(
    key="export",
    title_fa="موتور صادرات",
    source_ref=_EXPORT_SOURCE,
    capabilities=(
        _capability("E-01", "پذیرش تأمین‌کننده حرفه‌ای", _EXPORT_SOURCE),
        _capability("E-02", "تعریف محصول صادراتی", _EXPORT_SOURCE),
        _capability("E-03", "بررسی تقاضای بازار هدف", _EXPORT_SOURCE),
        _capability("E-04", "قرارداد تأمین", _EXPORT_SOURCE),
        _capability("E-05", "تحویل و کنترل کیفیت", _EXPORT_SOURCE),
        _capability("E-06", "فرآوری محصول", _EXPORT_SOURCE),
        _capability("E-07", "فروش خارجی", _EXPORT_SOURCE),
        _capability("E-08", "صادرات و تحویل", _EXPORT_SOURCE),
        _capability("E-09", "مالی و سهم درآمد صادرات", _EXPORT_SOURCE),
    ),
)

# This is an internal immutable registry, not a database or operating policy.
ENGINES: Final[tuple[Engine, Engine]] = (DOMESTIC, EXPORT)


def find_engine(key: str) -> Engine | None:
    """Exact engine match; no inferred cross-engine fallback."""
    for engine in ENGINES:
        if engine.key == key:
            return engine
    return None
