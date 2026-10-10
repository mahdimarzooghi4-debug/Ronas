"""Fixed Keycloak code-to-token HTTP adapter, opt-in only."""
import httpx
from .auth import InvalidToken
from .oidc_browser import BrowserOIDCConfig, _safe_string


class KeycloakCodeExchanger:
    def __init__(self, config: BrowserOIDCConfig, client: httpx.AsyncClient):
        self.config = config
        self.client = client
        self.endpoint = config.keycloak.issuer + "/protocol/openid-connect/token"

    async def __call__(self, code: str, verifier: str) -> dict:
        if not _safe_string(code, 2048) or not _safe_string(verifier, 128):
            raise InvalidToken
        try:
            result = await self.client.post(
                self.endpoint,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.config.keycloak.browser_client_id,
                    "redirect_uri": self.config.callback_url,
                    "code": code,
                    "code_verifier": verifier,
                },
                headers={"Accept": "application/json"},
                follow_redirects=False,
                timeout=5.0,
            )
            if (result.status_code != 200 or len(result.content) > 65536
                    or "application/json" not in result.headers.get("content-type", "").lower()):
                raise InvalidToken
            body = result.json()
            if not isinstance(body, dict) or body.get("token_type") != "Bearer":
                raise InvalidToken
            access, identity = body.get("access_token"), body.get("id_token")
            if not _safe_string(access, 12000) or not _safe_string(identity, 12000):
                raise InvalidToken
            return {"token_type": "Bearer", "access_token": access, "id_token": identity}
        except (httpx.HTTPError, ValueError, TypeError, InvalidToken) as exc:
            raise InvalidToken from exc
