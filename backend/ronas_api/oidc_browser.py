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
from urllib.parse import urlencode, urlsplit

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


@dataclass(frozen=True)
class BrowserSession:
    subject: str
    roles: frozenset[str]
    access_token: str
    csrf: str
    expires_at: int


class BrowserSessionStore(Protocol):
    """Must atomically consume login state; must scope, expire and revoke sessions."""

    def save_pending(self, item: PendingLogin) -> None: ...
    def take_pending(self, state: str) -> PendingLogin | None: ...
    def save_session(self, sid: str, session: BrowserSession) -> None: ...
    def get_session(self, sid: str) -> BrowserSession | None: ...
    def revoke_session(self, sid: str) -> None: ...


class CodeExchanger(Protocol):
    async def __call__(self, code: str, verifier: str) -> dict: ...


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
                 exchange: CodeExchanger, now: Callable[[], float] = time.time):
        self.config = config
        self.store = store
        self.exchange = exchange
        self.now = now
        self.access_verifier = KeycloakTokenVerifier(config.keycloak)

    def start(self) -> tuple[str, str]:
        state, verifier, nonce = _opaque(), _opaque(48), _opaque()
        self.store.save_pending(PendingLogin(state, verifier, nonce, self.now()))
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

    async def finish(self, code: str, state: str, state_cookie: str | None) -> str:
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
            access_claims = jwt.decode(bundle["access_token"],
                                       options={"verify_signature": False})
            expires_at = access_claims["exp"]
            if type(expires_at) is not int or expires_at <= int(self.now()):
                raise InvalidToken
            # Local technical bound; not a business retention decision.
            expires_at = min(expires_at, int(self.now()) + 900)
            sid = _opaque(36)
            self.store.save_session(sid, BrowserSession(
                principal.subject, principal.roles,
                bundle["access_token"], _opaque(), expires_at,
            ))
            return sid
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


def build_browser_router(flow: BrowserOIDC) -> APIRouter:
    router = APIRouter()
    name = "__Host-ronas_session"
    pending_name = "__Host-ronas_login"

    @router.get("/api/auth/start")
    def start():
        url, state = flow.start()
        resp = RedirectResponse(url, status_code=303)
        resp.set_cookie(pending_name, state, max_age=300,
                        secure=True, httponly=True, samesite="lax", path="/")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @router.get("/api/auth/callback")
    async def callback(code: str = "", state: str = "",
                       cookie: str | None = Cookie(default=None, alias=pending_name)):
        try:
            sid = await flow.finish(code, state, cookie)
        except InvalidToken:
            raise HTTPException(status_code=401, detail="OIDC_CALLBACK_REJECTED") from None
        resp = RedirectResponse(flow.config.return_path, status_code=303)
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
        return {"subject": record.subject, "roles": sorted(record.roles), "csrf": record.csrf}

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

    return router
