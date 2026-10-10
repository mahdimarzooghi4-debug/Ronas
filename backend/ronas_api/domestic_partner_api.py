"""Signed read-only Domestic partner DEMO self-views, strictly opt-in."""
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal
from .domestic_partner_workspace import (
    ROLES, SyntheticDomesticPartnerUnavailable, SyntheticDomesticPartnerWorkspace,
)


def build_domestic_partner_router(
    workspace: SyntheticDomesticPartnerWorkspace,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    if not isinstance(workspace, SyntheticDomesticPartnerWorkspace):
        raise ValueError("explicit synthetic Domestic partner workspace required")
    router = APIRouter()

    @router.get("/api/v1/local-buyer/my-preview")
    def buyer_preview(p: Principal = Depends(verified_principal)) -> dict:
        return _own("local_buyer", p)

    @router.get("/api/v1/equipment-seller/my-preview")
    def equipment_preview(p: Principal = Depends(verified_principal)) -> dict:
        return _own("equipment_seller", p)

    def _own(role: str, principal: Principal) -> dict:
        if role not in ROLES:
            raise HTTPException(404, detail="PREVIEW_NOT_FOUND")
        try:
            preview = workspace.own_preview(role, principal)
        except SyntheticDomesticPartnerUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="DOMESTIC_PARTNER_PREVIEW_UNAVAILABLE",
            ) from exc
        if preview is None:
            raise HTTPException(status_code=404, detail="PREVIEW_NOT_FOUND")
        return preview

    return router
