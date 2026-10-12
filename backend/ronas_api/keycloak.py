"""Validate tokens issued by the approved, self-hosted Keycloak realm.

Only offline, operator-mounted PUBLIC JWKS is trusted; never follow a token
header URL, and never infer grants from realm/client UI labels.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
import jwt

from .auth import ALL_ROLES, InvalidToken, Principal


def _identifier(value):
    return (isinstance(value, str) and 0 < len(value) <= 128 and value.isascii()
            and all(c.isalnum() or c in "-_" for c in value))


def _public_keys(raw):
    if not isinstance(raw, bytes) or len(raw) > 65536:
        raise ValueError("bounded public JWKS required")
    try:
        document = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("malformed JWKS") from exc
    if not isinstance(document, dict) or set(document) != {"keys"}:
        raise ValueError("only JWKS keys expected")
    records = document["keys"]
    if not isinstance(records, list) or not 1 <= len(records) <= 8:
        raise ValueError("one to eight public signing keys required")
    keys = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("JWK must be an object")
        kid = record.get("kid")
        if not _identifier(kid) or kid in keys:
            raise ValueError("invalid or duplicate signing key id")
        if record.get("kty") != "RSA" or record.get("use", "sig") != "sig" or record.get("alg", "RS256") != "RS256":
            raise ValueError("RSA RS256 signing keys only")
        if not isinstance(record.get("n"), str) or not isinstance(record.get("e"), str):
            raise ValueError("RSA public modulus and exponent required")
        if any(x in record for x in ("d", "p", "q", "dp", "dq", "qi", "k", "oth")):
            raise ValueError("private key in JWKS")
        try:
            key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(record))
        except (ValueError, TypeError, jwt.PyJWTError) as exc:
            raise ValueError("invalid RSA JWK") from exc
        if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
            raise ValueError("2048-bit minimum public RSA key")
        keys[kid] = key
    return MappingProxyType(keys)


@dataclass(frozen=True)
class KeycloakConfig:
    issuer: str
    api_client_id: str
    browser_client_id: str
    jwks_json: bytes

    def __post_init__(self):
        parsed = urlsplit(self.issuer)
        segments = parsed.path.strip("/").split("/")
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or
                parsed.password is not None or parsed.query or parsed.fragment or parsed.path.endswith("/") or
                len(segments) < 2 or segments[-2] != "realms" or not _identifier(segments[-1]) or
                any(c.isspace() for c in self.issuer)):
            raise ValueError("exact Keycloak HTTPS realm issuer required")
        if (not _identifier(self.api_client_id) or not _identifier(self.browser_client_id)
                or self.api_client_id == self.browser_client_id):
            raise ValueError("distinct API and browser OIDC client IDs required")
        _public_keys(self.jwks_json)

    @classmethod
    def from_environment(cls):
        names = ("RONAS_KEYCLOAK_ISSUER", "RONAS_KEYCLOAK_API_CLIENT_ID",
                 "RONAS_KEYCLOAK_BROWSER_CLIENT_ID", "RONAS_KEYCLOAK_JWKS_FILE")
        values = [os.environ.get(n, "") for n in names]
        if any(not v.strip() for v in values):
            return None
        path = Path(values[3])
        if not path.is_absolute() or not path.is_file():
            return None
        try:
            return cls(values[0], values[1], values[2], path.read_bytes())
        except (ValueError, OSError, TypeError):
            return None


class KeycloakTokenVerifier:
    def __init__(self, config: KeycloakConfig):
        self.config = config
        self.keys = _public_keys(config.jwks_json)

    def verify(self, token):
        try:
            if not isinstance(token, str) or not token or len(token) > 12000:
                raise InvalidToken
            header = jwt.get_unverified_header(token)
            if (header.get("alg") != "RS256" or header.get("kid") not in self.keys or
                    any(c in header for c in ("crit", "jku", "jwk", "x5u", "x5c"))):
                raise InvalidToken
            claims = jwt.decode(
                token, self.keys[header["kid"]], algorithms=["RS256"],
                issuer=self.config.issuer, audience=self.config.api_client_id,
                options={"require": ["iss", "aud", "sub", "exp", "iat", "nbf", "azp", "typ"],
                         "strict_aud": False}, leeway=0,
            )
            if any(type(claims.get(k)) is not int for k in ("exp", "iat", "nbf")):
                raise InvalidToken
            aud = claims.get("aud")
            if type(aud) is str:
                accepted_aud = aud == self.config.api_client_id
            elif type(aud) is list:
                accepted_aud = (bool(aud) and all(type(a) is str and a for a in aud)
                                and len(aud) == len(set(aud)) and self.config.api_client_id in aud)
            else:
                accepted_aud = False
            if not accepted_aud or claims.get("azp") != self.config.browser_client_id or claims.get("typ") != "Bearer":
                raise InvalidToken
            sub = claims.get("sub")
            resources = claims.get("resource_access")
            client = resources.get(self.config.api_client_id) if isinstance(resources, dict) else None
            roles = client.get("roles") if isinstance(client, dict) else None
            if (not isinstance(sub, str) or not sub.strip() or len(sub) > 256 or
                    not isinstance(roles, list) or not 1 <= len(roles) <= len(ALL_ROLES) or
                    any(type(r) is not str or r not in ALL_ROLES for r in roles) or
                    len(roles) != len(set(roles))):
                raise InvalidToken
            return Principal(subject=sub, roles=frozenset(roles))
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, InvalidToken) as exc:
            raise InvalidToken from exc
