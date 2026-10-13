"""Keycloak Authorization Code + PKCE BFF contract.

The default Ronas app does NOT mount browser login. Only an explicitly injected
server-side session store and code exchanger can activate this router. No
browser-held access tokens, mock users, real PII, or external IdP defaults.
"""
import base64
from dataclasses import dataclass
import hashlib
import hmac
import secrets
import time
from typing import Awaitable, Callable, Protocol
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
from fastapi import APIRouter, Cookie, Header, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from .auth import InvalidToken, Principal
from .keycloak import KeycloakConfig, KeycloakTokenVerifier


def _opaque(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


def _challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def _safe_string(v: object, length: int = 512) -> bool:
    return isinstance(v, str) and 0 < len(v) <= length and all(c.isascii() and not c.isspace() for c in v)


@dataclass(frozen=True)
class PendingLogin:
    state: str
    verifier: str
    nonce: str
    created_at: float
    return_path: str = "/"

    def __post_init__(self) -> None:
        if self.return_path not in ("/", "/admin"):
            raise ValueError("fixed local post-login destination required")


@dataclass(frozen=True)
class BrowserSession:
    subject: str
    roles: frozenset[str]
    access_token: str
    csrf: str
    expires_at: int
    id_token: str = ""
    refresh_token: str = ""


class BrowserSessionStore(Protocol):
    """Must atomically consume login state; must scope, expire and revoke sessions."""

    def save_pending(self, item: PendingLogin) -> None: ...
    def take_pending(self, state: str) -> PendingLogin | None: ...
    def save_session(self, sid: str, session: BrowserSession) -> None: ...
    def get_session(self, sid: str) -> BrowserSession | None: ...
    def revoke_session(self, sid: str) -> None: ...
    def begin_refresh(self, sid: str, lease: str) -> bool: ...
    def complete_refresh(self, sid: str, lease: str, session: BrowserSession) -> bool: ...
    def release_refresh(self, sid: str, lease: str) -> None: ...


class CodeExchanger(Protocol):
    async def __call__(self, code: str, verifier: str) -> dict: ...


class RefreshExchanger(Protocol):
    async def __call__(self, refresh_token: str) -> dict: ...


class RefreshBusy(Exception):
    """Another API worker currently owns the refresh-token rotation lease."""


@dataclass(frozen=True)
class BrowserOIDCConfig:
    keycloak: KeycloakConfig
    callback_url: str
    return_path: str = "/"

    def __post_init__(self):
        p = urlsplit(self.callback_url)
        if (p.scheme != "https" or not p.netloc or not p.hostname or p.username or p.password
                or p.query or p.fragment or p.path != "/api/auth/callback"
                or self.return_path not in ("/", "/admin")):
            raise ValueError("fixed HTTPS callback and local return path required")

    @property
    def origin(self) -> str:
        p = urlsplit(self.callback_url)
        return p.scheme + "://" + p.netloc


class BrowserOIDC:
    """No persistent in-memory store is implemented for operational use."""

    def __init__(self, config: BrowserOIDCConfig, store: BrowserSessionStore,
                 exchange: CodeExchanger, now: Callable[[], float] = time.time,
                 refresh_exchange: RefreshExchanger | None = None):
        self.config = config
        self.store = store
        self.exchange = exchange
        self.refresh_exchange = refresh_exchange
        self.now = now
        self.access_verifier = KeycloakTokenVerifier(config.keycloak)

    def start(self, return_path: str | None = None) -> tuple[str, str]:
        destination = self.config.return_path if return_path is None else return_path
        if destination not in ("/", "/admin"):
            raise ValueError("fixed local post-login destination required")
        state, verifier, nonce = _opaque(), _opaque(48), _opaque()
        self.store.save_pending(PendingLogin(
            state, verifier, nonce, self.now(), destination,
        ))
        params = {
            "client_id": self.config.keycloak.browser_client_id,
            "redirect_uri": self.config.callback_url,
            "response_type": "code",
            "scope": "openid",
            "state": state,
            "nonce": nonce,
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
        }
        return self.config.keycloak.issuer + "/protocol/openid-connect/auth?" + urlencode(params), state

    def _id_subject(self, token: str, expected_nonce: str) -> str:
        if not _safe_string(token, 12000):
            raise InvalidToken
        try:
            header = jwt.get_unverified_header(token)
            if (header.get("alg") != "RS256" or header.get("kid") not in self.access_verifier.keys
                    or any(name in header for name in ("crit", "jwk", "jku", "x5u", "x5c"))):
                raise InvalidToken
            claims = jwt.decode(
                token, self.access_verifier.keys[header["kid"]],
                algorithms=["RS256"], issuer=self.config.keycloak.issuer,
                audience=self.config.keycloak.browser_client_id,
                options={"require": ["iss", "aud", "sub", "exp", "iat", "nonce"],
                         "strict_aud": True}, leeway=0,
            )
            if (type(claims.get("exp")) is not int or type(claims.get("iat")) is not int
                    or claims.get("nonce") != expected_nonce
                    or claims.get("azp", self.config.keycloak.browser_client_id) != self.config.keycloak.browser_client_id
                    or claims.get("typ") == "Bearer"):
                raise InvalidToken
            sub = claims.get("sub")
            if not isinstance(sub, str) or not sub.strip() or len(sub) > 256:
                raise InvalidToken
            return sub
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, InvalidToken) as exc:
            raise InvalidToken from exc

    async def finish(
        self, code: str, state: str, state_cookie: str | None,
    ) -> tuple[str, str]:
        if (not _safe_string(code, 2048) or not _safe_string(state, 256)
                or not state_cookie or not hmac.compare_digest(state, state_cookie)):
            raise InvalidToken
        # Atomic take MUST happen before any network exchange: callback is single-use.
        pending = self.store.take_pending(state)
        if (pending is None or not hmac.compare_digest(pending.state, state)
                or not 0 <= self.now() - pending.created_at <= 300):
            raise InvalidToken
        try:
            bundle = await self.exchange(code, pending.verifier)
            if (not isinstance(bundle, dict) or bundle.get("token_type") != "Bearer"
                    or not _safe_string(bundle.get("access_token"), 12000)
                    or not _safe_string(bundle.get("id_token"), 12000)):
                raise InvalidToken
            principal = self.access_verifier.verify(bundle["access_token"])
            id_sub = self._id_subject(bundle["id_token"], pending.nonce)
            if not hmac.compare_digest(principal.subject, id_sub):
                raise InvalidToken
            signed_token = bundle["access_token"]
            key_id = jwt.get_unverified_header(signed_token)["kid"]
            access_claims = jwt.decode(
                signed_token,
                self.access_verifier.keys[key_id],
                algorithms=["RS256"],
                issuer=self.config.keycloak.issuer,
                audience=self.config.keycloak.api_client_id,
                options={"require": ["iss", "aud", "exp", "iat", "nbf"],
                         "verify_exp": True, "verify_nbf": True,
                         "verify_iat": True},
                leeway=0,
            )
            expires_at = access_claims["exp"]
            if type(expires_at) is not int or expires_at <= int(self.now()):
                raise InvalidToken
            # Local technical bound; not a business retention decision.
            expires_at = min(expires_at, int(self.now()) + 900)
            sid = _opaque(36)
            self.store.save_session(sid, BrowserSession(
                principal.subject, principal.roles,
                bundle["access_token"], _opaque(), expires_at,
                bundle["id_token"], bundle.get("refresh_token", ""),
            ))
            destination = pending.return_path
            admin_roles = {"domestic_ops", "export_ops", "finance", "governance"}
            if destination == "/admin" and not principal.roles.intersection(admin_roles):
                destination = "/"
            return sid, destination
        except (InvalidToken, jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
            raise InvalidToken from exc

    def session(self, sid: str | None) -> BrowserSession:
        if not sid or not _safe_string(sid, 180):
            raise InvalidToken
        existing = self.store.get_session(sid)
        if existing is None or existing.expires_at <= int(self.now()):
            raise InvalidToken
        user = self.access_verifier.verify(existing.access_token)
        if user.subject != existing.subject or user.roles != existing.roles:
            raise InvalidToken
        return existing


    async def refresh_session(self, sid: str) -> BrowserSession:
        if self.refresh_exchange is None:
            raise InvalidToken
        current = self.session(sid)
        if not _safe_string(current.refresh_token, 12000):
            raise InvalidToken
        lease = _opaque()
        if not self.store.begin_refresh(sid, lease):
            raise RefreshBusy
        committed = False
        try:
            bundle = await self.refresh_exchange(current.refresh_token)
            if (not isinstance(bundle, dict) or bundle.get("token_type") != "Bearer"
                    or not _safe_string(bundle.get("access_token"), 12000)):
                raise InvalidToken
            rotated = bundle.get("refresh_token", current.refresh_token)
            if not _safe_string(rotated, 12000):
                raise InvalidToken
            principal = self.access_verifier.verify(bundle["access_token"])
            if not hmac.compare_digest(principal.subject, current.subject):
                raise InvalidToken
            key_id = jwt.get_unverified_header(bundle["access_token"])["kid"]
            claims = jwt.decode(
                bundle["access_token"], self.access_verifier.keys[key_id],
                algorithms=["RS256"], issuer=self.config.keycloak.issuer,
                audience=self.config.keycloak.api_client_id,
                options={"require": ["iss", "aud", "sub", "exp", "iat", "nbf"],
                         "strict_aud": False}, leeway=0,
            )
            expires_at = claims.get("exp")
            if type(expires_at) is not int or expires_at <= int(self.now()):
                raise InvalidToken
            expires_at = min(expires_at, int(self.now()) + 900)
            renewed = BrowserSession(
                principal.subject, principal.roles, bundle["access_token"],
                _opaque(), expires_at, current.id_token, rotated,
            )
            if not self.store.complete_refresh(sid, lease, renewed):
                raise InvalidToken
            committed = True
            return renewed
        except Exception as exc:
            # A rotating grant may have reached Keycloak; do not retry a possibly consumed token.
            self.store.revoke_session(sid)
            if isinstance(exc, InvalidToken):
                raise
            raise InvalidToken from exc
        finally:
            if not committed:
                self.store.release_refresh(sid, lease)


def build_browser_router(flow: BrowserOIDC) -> APIRouter:
    router = APIRouter()
    name = "__Host-ronas_session"
    pending_name = "__Host-ronas_login"

    @router.get("/api/auth/start")
    def start(return_to: str | None = None):
        try:
            url, state = flow.start(return_to)
        except ValueError:
            raise HTTPException(status_code=422, detail="INVALID_LOCAL_RETURN_PATH") from None
        resp = RedirectResponse(url, status_code=303)
        resp.set_cookie(pending_name, state, max_age=300,
                        secure=True, httponly=True, samesite="lax", path="/")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @router.get("/api/auth/callback")
    async def callback(code: str = "", state: str = "",
                       cookie: str | None = Cookie(default=None, alias=pending_name)):
        try:
            sid, return_path = await flow.finish(code, state, cookie)
        except InvalidToken:
            raise HTTPException(status_code=401, detail="OIDC_CALLBACK_REJECTED") from None
        resp = RedirectResponse(return_path, status_code=303)
        resp.delete_cookie(pending_name, path="/", secure=True, httponly=True, samesite="lax")
        resp.set_cookie(name, sid, max_age=900,
                        secure=True, httponly=True, samesite="lax", path="/")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @router.get("/api/auth/session")
    def session(cookie: str | None = Cookie(default=None, alias=name)):
        try:
            record = flow.session(cookie)
        except InvalidToken:
            raise HTTPException(status_code=401, detail="NO_ACTIVE_SESSION") from None
        return {"subject": record.subject, "roles": sorted(record.roles), "csrf": record.csrf,
                "expires_at": record.expires_at}

    @router.post("/api/auth/refresh")
    async def refresh(
        request: Request,
        cookie: str | None = Cookie(default=None, alias=name),
        csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None, alias="Origin"),
    ):
        if origin != flow.config.origin:
            raise HTTPException(status_code=403, detail="ORIGIN_REQUIRED")
        try:
            current = flow.session(cookie)
        except InvalidToken:
            raise HTTPException(status_code=401, detail="NO_ACTIVE_SESSION") from None
        if not csrf or not hmac.compare_digest(current.csrf, csrf):
            raise HTTPException(status_code=403, detail="CSRF_REQUIRED")
        try:
            renewed = await flow.refresh_session(cookie)
        except RefreshBusy:
            raise HTTPException(status_code=409, detail="SESSION_REFRESH_IN_PROGRESS") from None
        except InvalidToken:
            if cookie:
                flow.store.revoke_session(cookie)
            response = Response(status_code=401)
            response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")
            response.headers["Cache-Control"] = "no-store"
            return response
        response = JSONResponse({
            "roles": sorted(renewed.roles), "csrf": renewed.csrf,
            "expires_at": renewed.expires_at,
        })
        response.set_cookie(name, cookie, max_age=max(1, renewed.expires_at - int(flow.now())),
                            secure=True, httponly=True, samesite="lax", path="/")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @router.post("/api/auth/logout")
    def logout(request: Request, response: Response,
               cookie: str | None = Cookie(default=None, alias=name),
               csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
               origin: str | None = Header(default=None, alias="Origin")):
        if origin != flow.config.origin:
            raise HTTPException(status_code=403, detail="ORIGIN_REQUIRED")
        try:
            record = flow.session(cookie)
        except InvalidToken:
            raise HTTPException(status_code=401, detail="NO_ACTIVE_SESSION") from None
        if not csrf or not hmac.compare_digest(record.csrf, csrf):
            raise HTTPException(status_code=403, detail="CSRF_REQUIRED")
        flow.store.revoke_session(cookie)
        response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")
        return {"session": "closed"}

    @router.post("/api/auth/logout/keycloak")
    async def keycloak_logout(
        request: Request,
        cookie: str | None = Cookie(default=None, alias=name),
        csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
        origin: str | None = Header(default=None, alias="Origin"),
    ):
        if origin != flow.config.origin:
            raise HTTPException(status_code=403, detail="ORIGIN_REQUIRED")
        try:
            record = flow.session(cookie)
        except InvalidToken:
            raise HTTPException(status_code=401, detail="NO_ACTIVE_SESSION") from None
        csrf = csrf_header
        if not csrf and request.headers.get("content-type", "").split(";", 1)[0].strip() == (
            "application/x-www-form-urlencoded"
        ):
            declared = request.headers.get("content-length")
            if declared:
                try:
                    if int(declared) > 2048:
                        raise HTTPException(status_code=413, detail="LOGOUT_REQUEST_TOO_LARGE")
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail="INVALID_LOGOUT_REQUEST") from exc
            chunks = bytearray()
            async for chunk in request.stream():
                chunks.extend(chunk)
                if len(chunks) > 2048:
                    raise HTTPException(status_code=413, detail="LOGOUT_REQUEST_TOO_LARGE")
            try:
                fields = parse_qs(bytes(chunks).decode("ascii"), strict_parsing=True)
                csrf_values = fields.get("csrf", [])
                csrf = csrf_values[0] if len(csrf_values) == 1 else None
            except (UnicodeDecodeError, ValueError):
                raise HTTPException(status_code=400, detail="INVALID_LOGOUT_REQUEST") from None
        if not csrf or not hmac.compare_digest(record.csrf, csrf):
            raise HTTPException(status_code=403, detail="CSRF_REQUIRED")
        if not record.id_token:
            raise HTTPException(status_code=503, detail="ID_TOKEN_LOGOUT_HINT_UNAVAILABLE")
        state = _opaque()
        logout_uri = (
            flow.config.keycloak.issuer.rstrip("/")
            + "/protocol/openid-connect/logout?"
            + urlencode({
                "id_token_hint": record.id_token,
                "client_id": flow.config.keycloak.browser_client_id,
                "post_logout_redirect_uri":
                    flow.config.origin + "/api/auth/logout/callback",
                "state": state,
            })
        )
        # Revoke locally before sending the browser to the provider. If the
        # provider is unreachable or the user cancels, Ronas stays signed out.
        flow.store.revoke_session(cookie)
        response = RedirectResponse(logout_uri, status_code=303)
        response.delete_cookie(
            name, path="/", secure=True, httponly=True, samesite="lax",
        )
        response.set_cookie(
            "__Host-ronas_logout", state, max_age=300, secure=True,
            httponly=True, samesite="lax", path="/",
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @router.get("/api/auth/logout/callback")
    def keycloak_logout_callback(
        state: str = "",
        logout_state: str | None = Cookie(default=None, alias="__Host-ronas_logout"),
    ):
        if (not _safe_string(state, 180) or not _safe_string(logout_state, 180)
                or not hmac.compare_digest(state, logout_state)):
            raise HTTPException(status_code=400, detail="LOGOUT_CALLBACK_REJECTED")
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(
            "__Host-ronas_logout", path="/", secure=True,
            httponly=True, samesite="lax",
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    return router
