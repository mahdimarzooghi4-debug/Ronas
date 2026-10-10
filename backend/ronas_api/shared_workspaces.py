"""Canonical LOCAL/TEST user-partner role-workspace projection.

Navigation metadata is derived ONLY from server-verified role claims.
It cannot grant a case, authorize a Business activity, or treat a synthetic
read-model as a real service. Exactly two UI environments are supported.
"""
from collections.abc import Callable
from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal

USER_ROLES = {
    "household": "خانوار / تولیدکننده خانگی",
    "local_buyer": "خریدار محلی",
    "agronomy_expert": "کارشناس کشاورزی",
    "equipment_seller": "فروشنده تجهیزات",
    "export_supplier": "تأمین‌کننده حرفه‌ای صادرات",
}


def visible_user_workspaces(
    principal: Principal, *, owned_cases: bool = False,
    technical_progress: bool = False,
) -> list[dict]:
    """No role is inferred from another; no case is read on this endpoint."""
    if not isinstance(principal, Principal):
        return []
    workspaces = []
    for role, label in USER_ROLES.items():
        if role not in principal.roles:
            continue
        reads = []
        if role == "household" and owned_cases:
            reads.append("OWNED_SYNTHETIC_DOMESTIC_DRAFTS")
            if technical_progress:
                reads.append("OWNED_SYNTHETIC_TECHNICAL_PROGRESS")
        workspaces.append({
            "role": role,
            "label": label,
            "environment": "SHARED_USER_PARTNER",
            "activity_state": "NOT_OPERATIONAL",
            "business_actions_enabled": False,
            "local_test_reads": reads,
        })
    return workspaces


def build_user_workspaces_router(
    verified_principal: Callable[..., Principal], *,
    owned_cases: bool = False, technical_progress: bool = False,
) -> APIRouter:
    """Opt-in read-only API; caller principal MUST be Keycloak-verified."""
    router = APIRouter()

    @router.get("/api/v1/me/user-workspaces")
    def all_workspaces(p: Principal = Depends(verified_principal)) -> dict:
        return {
            "environment": "SHARED_USER_PARTNER",
            "items": visible_user_workspaces(
                p, owned_cases=owned_cases, technical_progress=technical_progress,
            ),
        }

    @router.get("/api/v1/me/user-workspaces/{role}")
    def one_workspace(
        role: str, p: Principal = Depends(verified_principal),
    ) -> dict:
        found = next((
            w for w in visible_user_workspaces(
                p, owned_cases=owned_cases, technical_progress=technical_progress,
            ) if w["role"] == role
        ), None)
        if found is None:
            # Unknown and signed-but-unassigned roles are indistinguishable.
            raise HTTPException(status_code=404, detail="WORKSPACE_NOT_FOUND")
        return found

    return router
