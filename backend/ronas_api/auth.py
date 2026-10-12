"""Strict, offline public-key verifier for externally issued RS256 access tokens.

No sign-in, token minting, testing bypass, automatic role assignment or discovery
of an Identity Provider is implemented here. Never trust X-Role or unsigned JWTs.
"""
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import HTTPException, status

ALL_ROLES = frozenset({
    "household", "local_buyer", "agronomy_expert", "equipment_seller",
    "export_supplier", "domestic_ops", "export_ops", "finance", "governance",
})


@dataclass(frozen=True)
class AuthConfig:
    issuer: str
    audience: str
    key_id: str
    public_key_pem: bytes

    def __post_init__(self) -> None:
        if not self.issuer.startswith("https://") or not self.audience.strip() or not self.key_id.strip():
            raise ValueError("exact HTTPS issuer, audience and key identifier required")
        key = load_pem_public_key(self.public_key_pem)
        if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
            raise ValueError("an RSA public key of at least 2048 bits is required")

    @classmethod
    def from_environment(cls) -> "AuthConfig | None":
        # Missing config is a disabled backend, NOT a development auth fallback.
        names = ["RONAS_OIDC_ISSUER", "RONAS_OIDC_AUDIENCE",
                 "RONAS_OIDC_KEY_ID", "RONAS_OIDC_PUBLIC_KEY_FILE"]
        values = [os.environ.get(k, "") for k in names]
        if any(not value.strip() for value in values):
            return None
        path = Path(values[3])
        if not path.is_absolute() or not path.is_file():
            return None
        try:
            return cls(values[0], values[1], values[2], path.read_bytes())
        except (OSError, ValueError, TypeError):
            return None


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[str]


class InvalidToken(Exception):
    pass


class TokenVerifier:
    def __init__(self, config: AuthConfig):
        self.config = config

    def verify(self, raw: str) -> Principal:
        try:
            if not isinstance(raw, str) or not raw or len(raw) > 12000:
                raise InvalidToken
            header: dict[str, Any] = jwt.get_unverified_header(raw)
            if header.get("alg") != "RS256" or header.get("kid") != self.config.key_id:
                raise InvalidToken
            if header.get("crit") or header.get("jku") or header.get("jwk") or header.get("x5u"):
                raise InvalidToken
            payload: dict[str, Any] = jwt.decode(
                raw,
                self.config.public_key_pem,
                algorithms=["RS256"],
                issuer=self.config.issuer,
                audience=self.config.audience,
                options={"require": ["sub", "iss", "aud", "exp", "iat", "nbf"],
                         "verify_exp": True, "verify_nbf": True, "verify_iat": True,
                         "strict_aud": True},
                leeway=0,
            )
            if any(type(payload.get(name)) is not int for name in ("exp", "iat", "nbf")):
                raise InvalidToken
            subject = payload.get("sub")
            roles = payload.get("ronas_roles")
            if not isinstance(subject, str) or not subject.strip() or len(subject) > 256:
                raise InvalidToken
            if not isinstance(roles, list) or not roles or len(roles) > len(ALL_ROLES):
                raise InvalidToken
            if any(not isinstance(r, str) or r not in ALL_ROLES for r in roles):
                raise InvalidToken
            if len(roles) != len(set(roles)):
                raise InvalidToken
            return Principal(subject=subject, roles=frozenset(roles))
        except (jwt.PyJWTError, ValueError, TypeError, InvalidToken) as err:
            raise InvalidToken from err


def require_role(principal: Principal, role: str) -> None:
    if role not in principal.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="FORBIDDEN")
