"""Pinned, DRAFT business-evidence snapshot; no gate decision or live workflow.

This is a version-specific transcription of source-document issue IDs/statuses.
It is NOT a production gate evaluator, approval system, policy threshold,
or current authoritative state once Business PR #1 has advanced.
"""
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal

BUSINESS_SOURCE_SHA = "5492690e91955e64353824ffa4ec3250286fdf68"
SNAPSHOT_STATE = "PINNED_DRAFT_SNAPSHOT_NOT_LIVE"
REVIEW_AUTHORITY = "UNASSIGNED"
ACTIONS_ENABLED = False

@dataclass(frozen=True)
class GateEvidence:
    evidence_id: str
    label: str
    source_status: str

@dataclass(frozen=True)
class GateDossier:
    domain: str
    role: str
    gate_issue: int
    source_path: str
    evidence: tuple[GateEvidence, ...]

_DOM = "docs/business/73-core-d1-e0-limited-scope-gate-decision-sheet.md"
_FIN = "docs/business/61-finance-legal-evidence-workstreams-for-d0-e0.md"

DOSSIERS = (
    GateDossier("DOMESTIC", "domestic_ops", 2, _DOM, (
        GateEvidence("D1-B-01", "مخاطب، منطقه و محصول", "OPEN / NO PILOT SELECTED"),
        GateEvidence("D1-B-02", "رضایت و حقوق داده", "OPEN / NO AUTHORITATIVE TERMS"),
        GateEvidence("D1-B-03", "صلاحیت متخصص واقعی", "OPEN / NO QUALIFIED REVIEWER VERIFIED"),
        GateEvidence("D1-B-04", "اجرای داخلی AI و بازبینی برنامه",
                     "AI GOVERNANCE APPROVED; REAL MODEL/RUNTIME/EVALUATION NOT READY"),
        GateEvidence("D1-B-05", "مشاهدات، تاریخچه و مسئولیت اصلاح", "OPEN"),
        GateEvidence("D1-B-06", "خروجی خدمت و تصمیم انسانی گیت", "NOT ACCEPTED / #2 OPEN"),
    )),
    GateDossier("EXPORT", "export_ops", 3, _DOM, (
        GateEvidence("E0-B-01", "پرسش پژوهش محصول–مقصد", "OPEN / NONE SELECTED"),
        GateEvidence("E0-B-02", "حق استفاده و نسخه منابع",
                     "GENERAL SOURCE SCREEN ONLY, NOT APPROVED FOR RONAS USE"),
        GateEvidence("E0-B-03", "مسئول و بازبین معتبر", "OPEN / NO REVIEWER VERIFIED"),
        GateEvidence("E0-B-04", "تمایز پژوهش از معامله",
                     "PRINCIPLE DEFINED; CONTRACT NOT APPROVED"),
        GateEvidence("E0-B-05", "شواهد و خروجی گزارش", "PROPOSED / NO ACCEPTANCE"),
        GateEvidence("E0-B-06", "گیت و جداسازی داده", "#3 OPEN"),
    )),
    GateDossier("FINANCE", "finance", 4, _FIN, (
        GateEvidence("FIN-001", "دامنه Domestic و Export", "OPEN / NO VALIDATED MODEL"),
        GateEvidence("FIN-002", "طبقه‌بندی سرمایه و هزینه", "OPEN / NO CORRECTED FIGURE"),
        GateEvidence("FIN-003", "تعریف اعضا و حق عضویت", "OPEN / NO FEE APPROVED"),
        GateEvidence("FIN-004", "درآمد و روابط قراردادی Export", "OPEN / NO MODEL SELECTED"),
        GateEvidence("FIN-005", "منبع نرخ، قیمت و هزینه", "OPEN / NO PRICE VERIFIED"),
        GateEvidence("FIN-006", "جریان نقدی و تعهدات", "OPEN / NO CASHFLOW APPROVED"),
        GateEvidence("FIN-007", "اقتصاد واحد و هزینه خدمات", "OPEN / NO UNIT ECONOMICS APPROVED"),
    )),
)

assert len(DOSSIERS) == 3
assert len({e.evidence_id for d in DOSSIERS for e in d.evidence}) == 19
assert all(d.evidence and d.source_path.startswith("docs/business/")
           for d in DOSSIERS)


def visible_dossiers(principal: Principal) -> tuple[GateDossier, ...]:
    if not isinstance(principal, Principal):
        return ()
    return tuple(
        d for d in DOSSIERS if d.role in principal.roles
        or "governance" in principal.roles
    )


def dossier_summary(dossier: GateDossier) -> dict:
    return {
        "domain": dossier.domain,
        "gate_issue": dossier.gate_issue,
        "gate_status_at_source": "OPEN",
        "snapshot_state": SNAPSHOT_STATE,
        "business_source_sha": BUSINESS_SOURCE_SHA,
        "actions_enabled": ACTIONS_ENABLED,
    }


def dossier_detail(dossier: GateDossier) -> dict:
    result = dossier_summary(dossier)
    result.update({
        "source_path": dossier.source_path,
        "review_authority": REVIEW_AUTHORITY,
        "evidence_items": [
            {"id": e.evidence_id, "label": e.label,
             "source_status": e.source_status, "verified_here": False}
            for e in dossier.evidence
        ],
    })
    return result


def build_business_gate_evidence_router(
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    """Read-only opt-in technical view, never a Business approval endpoint."""
    router = APIRouter()

    @router.get("/api/v1/admin/gate-evidence")
    def gate_list(p: Principal = Depends(verified_principal)) -> dict:
        available = visible_dossiers(p)
        if not available:
            raise HTTPException(status_code=403, detail="ADMIN_ROLE_REQUIRED")
        return {
            "snapshot_state": SNAPSHOT_STATE,
            "business_source_sha": BUSINESS_SOURCE_SHA,
            "items": [dossier_summary(d) for d in available],
        }

    @router.get("/api/v1/admin/gate-evidence/{domain}")
    def gate_detail(domain: str, p: Principal = Depends(verified_principal)) -> dict:
        allowed = next(
            (d for d in visible_dossiers(p) if d.domain == domain), None
        )
        if allowed is None:
            # Unknown and unassigned domains have indistinguishable responses.
            raise HTTPException(status_code=404, detail="GATE_DOSSIER_NOT_FOUND")
        return dossier_detail(allowed)

    return router
