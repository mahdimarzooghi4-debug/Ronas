"""Explicit single-host HTTPS loopback BFF composition for LOCAL/TEST only.

Wires approved self-hosted Keycloak token verification + real OIDC PKCE HTTP
exchange + encrypted server sessions + the existing *nonoperational* two-UI
FastAPI shell. This is NOT a production launcher or a substitute for rights,
consent, grant authority, enterprise session storage, or Business gate passes.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Callable, Mapping
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI

from .app import create_app
from .keycloak import KeycloakConfig
from .keycloak_exchange import KeycloakCodeExchanger
from .oidc_browser import BrowserOIDC, BrowserOIDCConfig
from .session_sqlite import SqliteBrowserSessionStore
from .expert_review_questions_sqlite import SqliteSyntheticExpertQuestionLedger
from .agronomy_workspace import SyntheticAgronomyWorkspace
from .household_input_profiles import HouseholdInputSchema, SqliteSyntheticHouseholdProfileLedger
from .domestic_stage_observation import CurrentStageContext
from .stage_observation_artifacts import StageArtifactStore


class LocalBFFConfigurationError(ValueError):
    """Invalid/missing explicit security config; no partially enabled app."""


@dataclass(frozen=True)
class LocalBFFSettings:
    keycloak: KeycloakConfig
    callback_url: str
    session_database: Path
    session_key_file: Path

    def __post_init__(self) -> None:
        if not isinstance(self.keycloak, KeycloakConfig):
            raise LocalBFFConfigurationError("operator-pinned Keycloak required")
        try:
            parsed = urlsplit(self.callback_url)
        except ValueError as exc:
            raise LocalBFFConfigurationError("invalid callback") from exc
        try:
            port = parsed.port
        except ValueError as exc:
            raise LocalBFFConfigurationError("invalid loopback HTTPS port") from exc
        if (parsed.scheme != "https"
                or port == 0
                or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
                or parsed.path != "/api/auth/callback"):
            raise LocalBFFConfigurationError(
                "LOCAL/TEST BFF must use explicit loopback HTTPS callback"
            )
        for path in (self.session_database, self.session_key_file):
            if (not isinstance(path, Path) or not path.is_absolute()
                    or path.is_symlink() or ".." in path.parts):
                raise LocalBFFConfigurationError("absolute private file required")

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None,
        keycloak: KeycloakConfig | None = None,
    ) -> LocalBFFSettings:
        values = os.environ if environ is None else environ
        if values.get("RONAS_LOCAL_BFF_ENABLE") != "LOCAL_TEST_ONLY":
            raise LocalBFFConfigurationError("LOCAL/TEST explicit opt-in missing")
        realm = keycloak if keycloak is not None else KeycloakConfig.from_environment()
        if realm is None:
            raise LocalBFFConfigurationError("Keycloak public issuer/JWKS unavailable")
        params = (
            "RONAS_LOCAL_BFF_CALLBACK_URL",
            "RONAS_LOCAL_BFF_SESSION_DATABASE",
            "RONAS_LOCAL_BFF_SESSION_KEY_FILE",
        )
        if any(not values.get(name) for name in params):
            raise LocalBFFConfigurationError("required local BFF configuration missing")
        return cls(
            realm, values[params[0]], Path(values[params[1]]),
            Path(values[params[2]]),
        )


def _private_session_key(path: Path) -> bytes:
    """File-only secret, no environment inline secret or repo fallback."""
    try:
        info = path.lstat()
        parent = path.parent.lstat()
        if (not stat.S_ISREG(info.st_mode)
                or stat.S_IMODE(info.st_mode) != 0o600
                or not stat.S_ISDIR(parent.st_mode)
                or stat.S_IMODE(parent.st_mode) & 0o077
                or (hasattr(os, "getuid")
                    and (info.st_uid != os.getuid()
                         or parent.st_uid != os.getuid()))):
            raise LocalBFFConfigurationError("private key file/parent permissions invalid")
        with path.open("rb") as file:
            key = file.read(33)
        if len(key) != 32:
            raise LocalBFFConfigurationError("AES-256 key file must contain 32 bytes")
        return key
    except OSError as exc:
        raise LocalBFFConfigurationError("private session key unavailable") from exc


def create_local_test_bff(
    settings: LocalBFFSettings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    case_ledger: SqliteSyntheticExpertQuestionLedger | None = None,
    agronomy_workspace: SyntheticAgronomyWorkspace | None = None,
    household_profile_schema: HouseholdInputSchema | None = None,
    household_profile_access_authority=None,
    household_stage_context_authority: Callable[[str], CurrentStageContext | None] | None = None,
    household_stage_artifact_store: StageArtifactStore | None = None,
) -> FastAPI:
    """Opt-in composed application. `transport` is injected only by tests.

    Existing offline *synthetic* cases may be explicitly injected for full
    end-to-end workflow testing. No case or assignment is ever inferred from
    a signed role or created by this factory. No real intake is enabled.
    HTTP code exchange occurs only after signed callback state consumption.
    """
    if not isinstance(settings, LocalBFFSettings):
        raise LocalBFFConfigurationError("complete local BFF settings required")
    if case_ledger is not None and not isinstance(
        case_ledger, SqliteSyntheticExpertQuestionLedger,
    ):
        raise LocalBFFConfigurationError("only existing synthetic case ledger allowed")
    if household_stage_artifact_store is not None and (
            not isinstance(case_ledger, SqliteSyntheticHouseholdProfileLedger)
            or household_profile_schema != case_ledger.profile_schema
            or not callable(household_profile_access_authority)
            or not callable(household_stage_context_authority)
            or not all(callable(getattr(household_stage_artifact_store, name, None))
                       for name in ("put", "get", "contains"))):
        raise LocalBFFConfigurationError(
            "stage uploads require the same explicit household profile ledger and authorities"
        )
    if agronomy_workspace is not None and (
        case_ledger is None
        or not isinstance(agronomy_workspace, SyntheticAgronomyWorkspace)
        or agronomy_workspace.ledger is not case_ledger
    ):
        raise LocalBFFConfigurationError("agronomy must share exact case ledger")
    # A private SQLite file under a publicly writable directory can be
    # replaced or redirected. The LOCAL/TEST session directory is therefore
    # required to be an already existing, owned and non-shared directory.
    try:
        directory = settings.session_database.parent.lstat()
        if (not stat.S_ISDIR(directory.st_mode)
                or stat.S_IMODE(directory.st_mode) & 0o077
                or (hasattr(os, "getuid")
                    and directory.st_uid != os.getuid())):
            raise LocalBFFConfigurationError("session directory must be private")
    except OSError as exc:
        raise LocalBFFConfigurationError("session directory unavailable") from exc
    key = _private_session_key(settings.session_key_file)
    store = SqliteBrowserSessionStore(settings.session_database, key)
    cfg = BrowserOIDCConfig(settings.keycloak, settings.callback_url)

    async def exchange(code: str, verifier: str) -> dict:
        # No third-party proxy inherited from developer environment. HTTPS
        # certificate validation is ON; redirects and untrusted token URLs
        # are not followed.
        async with httpx.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False,
        ) as client:
            return await KeycloakCodeExchanger(cfg, client)(code, verifier)

    flow = BrowserOIDC(cfg, store, exchange)
    app = create_app(
        settings.keycloak, browser_flow=flow,
        scoped_registry=case_ledger,
        technical_review_ledger=case_ledger,
        agronomy_workspace=agronomy_workspace,
        household_profile_schema=household_profile_schema,
        household_profile_access_authority=household_profile_access_authority,
        household_stage_context_authority=household_stage_context_authority,
        household_stage_artifact_store=household_stage_artifact_store,
    )
    app.state.ronas_local_test_only = True
    return app


def create_from_environment() -> FastAPI:
    # A separate module exposes app; importing production ronas_api.app never
    # reads these env vars, enables BFF, or creates session files.
    return create_local_test_bff(LocalBFFSettings.from_environment())
