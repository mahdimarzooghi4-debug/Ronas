import unittest
import httpx
from ronas_api.auth import InvalidToken
from ronas_api.keycloak_exchange import KeycloakCodeExchanger


class MockKeycloakExchangeTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_form_and_bounded_response(self):
        seen = []
        def handler(req):
            seen.append(req)
            return httpx.Response(200, json={
                "token_type": "Bearer", "access_token": "a.b.c",
                "id_token": "d.e.f", "refresh_token": "discard",
            })
        class Realm:
            issuer = "https://example.test/realms/test"
            browser_client_id = "test-web"
        class Config:
            keycloak = Realm()
            callback_url = "https://app.test/api/auth/callback"
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await KeycloakCodeExchanger(Config(), client)("code", "verifier")
        self.assertEqual(set(result), {"token_type", "access_token", "id_token"})
        self.assertEqual(len(seen), 1)
        self.assertEqual(str(seen[0].url), Realm.issuer + "/protocol/openid-connect/token")
        self.assertIn(b"code_verifier=verifier", seen[0].content)
        self.assertIn(b"grant_type=authorization_code", seen[0].content)

    async def test_error_response_fails_closed(self):
        class Realm:
            issuer = "https://example.test/realms/test"
            browser_client_id = "test-web"
        class Config:
            keycloak = Realm()
            callback_url = "https://app.test/api/auth/callback"
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda req: httpx.Response(401, json={"error": "invalid_grant"})
        )) as client:
            with self.assertRaises(InvalidToken):
                await KeycloakCodeExchanger(Config(), client)("code", "verifier")


if __name__ == "__main__":
    unittest.main()
