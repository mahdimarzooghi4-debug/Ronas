"""Security-first Ronas HTTP admission slice: signed tokens and read-only fixtures.

These routes are not operating household/market/export endpoints. All records
are synthetic and fixed: no live personal data ingestion or mutation routes.
"""
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Response, status
from .auth import AuthConfig, InvalidToken, Principal, TokenVerifier, require_role
from .keycloak import KeycloakConfig, KeycloakTokenVerifier
from .oidc_browser import BrowserOIDC, build_browser_router
from .ui_bff import build_authenticated_ui_router
from .scoped_drafts import ScopedSyntheticDraftRegistry, build_scoped_draft_router

DOMESTIC_EXAMPLE = {
    "engine": "DOMESTIC", "ref": "DEMO-H01", "status": "DEMO_EVIDENCE_REQUIRED",
    "real_consent_verified": False, "accepted": False, "expert_approved": False,
    "source": "SYNTHETIC_ONLY",
}
EXPORT_EXAMPLE = {
    "engine": "EXPORT", "ref": "DEMO-E01", "status": "DEMO_RIGHTS_UNVERIFIED",
    "product": None, "destination": None,
    "source_ref": "DEMO-SOURCE-01", "source_rights_verified": False,
    "buyer_verified": False, "contracted": False, "source": "SYNTHETIC_ONLY",
}

def create_app(config: AuthConfig | KeycloakConfig | None = None,
               browser_flow: BrowserOIDC | None = None,
               scoped_registry: ScopedSyntheticDraftRegistry | None = None) -> FastAPI:
    app = FastAPI(
        title="Ronas bounded read-only API foundation",
        docs_url=None, redoc_url=None, openapi_url=None,
    )
    verifier = (KeycloakTokenVerifier(config) if isinstance(config, KeycloakConfig)
                else TokenVerifier(config) if isinstance(config, AuthConfig)
                else None)
    if browser_flow is not None:
        if not isinstance(config, KeycloakConfig) or browser_flow.config.keycloak != config:
            raise ValueError("browser flow must use the same pinned Keycloak realm")
        app.include_router(build_browser_router(browser_flow))
        app.include_router(build_authenticated_ui_router(browser_flow))

    @app.middleware("http")
    async def security_response_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def principal(authorization: str | None = Header(default=None),
                  session_cookie: str | None = Cookie(default=None, alias="__Host-ronas_session")) -> Principal:
        if verifier is None:
            raise HTTPException(status_code=503, detail="IDENTITY_NOT_CONFIGURED")
        if authorization is None and browser_flow is not None and session_cookie:
            try:
                record = browser_flow.session(session_cookie)
                return Principal(record.subject, record.roles)
            except InvalidToken:
                raise HTTPException(status_code=401, detail="INVALID_SESSION") from None
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="AUTHENTICATION_REQUIRED",
                                headers={"WWW-Authenticate": "Bearer"})
        token = authorization[7:]
        if not token or " " in token:
            raise HTTPException(status_code=401, detail="AUTHENTICATION_REQUIRED",
                                headers={"WWW-Authenticate": "Bearer"})
        try:
            return verifier.verify(token)
        except InvalidToken:
            raise HTTPException(status_code=401, detail="INVALID_TOKEN",
                                headers={"WWW-Authenticate": "Bearer"}) from None

    if scoped_registry is not None:
        if not isinstance(config, KeycloakConfig):
            raise ValueError("record-scoped technical fixtures require Keycloak")
        app.include_router(build_scoped_draft_router(scoped_registry, principal))

    def grant(name: str):
        def dependency(p: Principal = Depends(principal)) -> Principal:
            require_role(p, name)
            return p
        return dependency

    @app.get("/healthz")
    def health() -> dict[str, str]:
        # Liveness only, NEVER a declaration of authentication/production readiness.
        return {"status": "alive"}

    @app.get("/readyz")
    def readiness(response: Response) -> dict[str, str]:
        if verifier is None:
            response.status_code = 503
            return {"status": "blocked", "reason": "IDENTITY_NOT_CONFIGURED"}
        return {"status": "auth_configuration_loaded", "scope": "READ_ONLY_SYNTHETIC"}

    @app.get("/api/v1/me")
    def me(p: Principal = Depends(principal)) -> dict:
        return {"subject": p.subject, "roles": sorted(p.roles)}

    @app.get("/api/v1/domestic/household-intake/example")
    def household_example(p: Principal = Depends(grant("household"))) -> dict:
        return dict(DOMESTIC_EXAMPLE)

    @app.get("/api/v1/admin/domestic/household-intake/example")
    def domestic_ops_example(p: Principal = Depends(grant("domestic_ops"))) -> dict:
        return dict(DOMESTIC_EXAMPLE)

    @app.get("/api/v1/admin/export/research/example")
    def export_ops_example(p: Principal = Depends(grant("export_ops"))) -> dict:
        return dict(EXPORT_EXAMPLE)

    @app.get("/api/v1/admin/finance/status")
    def finance_status(p: Principal = Depends(grant("finance"))) -> dict:
        return {"engine": "SEPARATED", "status": "NOT_OPERATIONAL",
                "payments_enabled": False, "settlements_enabled": False}

    @app.get("/api/v1/admin/governance/status")
    def governance_status(p: Principal = Depends(grant("governance"))) -> dict:
        return {"status": "NOT_OPERATIONAL", "automatic_approvals_enabled": False}

    return app


# Default runtime admits ONLY the approved Keycloak profile, not legacy generic OIDC.
# Missing real Keycloak issuer and operator-mounted PUBLIC JWKS deny every protected route.
app = create_app(KeycloakConfig.from_environment())
