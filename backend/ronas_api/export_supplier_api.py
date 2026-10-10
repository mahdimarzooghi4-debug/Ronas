"""Keycloak-verified LOCAL/TEST supplier self-preview, GET only."""
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal
from .export_supplier_workspace import (
    SyntheticSupplierUnavailable, SyntheticSupplierWorkspace,
)


def build_export_supplier_router(
    workspace: SyntheticSupplierWorkspace,
    verified_principal: Callable[..., Principal],
) -> APIRouter:
    if not isinstance(workspace, SyntheticSupplierWorkspace):
        raise ValueError("explicit synthetic supplier workspace required")
    router = APIRouter()

    @router.get("/api/v1/export-supplier/my-preview")
    def own_preview(p: Principal = Depends(verified_principal)) -> dict:
        try:
            result = workspace.own_preview(p)
        except SyntheticSupplierUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="SUPPLIER_PREVIEW_UNAVAILABLE",
            ) from exc
        if result is None:
            raise HTTPException(status_code=404, detail="PREVIEW_NOT_FOUND")
        return result

    return router
