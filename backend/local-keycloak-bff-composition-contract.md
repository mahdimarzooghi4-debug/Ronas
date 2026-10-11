# Ronas LOCAL/TEST — operator-configured Keycloak PKCE browser BFF

**Scope:** First-party self-hosted Keycloak approved in RON-DEC-032, one existing shared user/collaborator environment plus one existing admin environment. Both are only non-operational **LOCAL/TEST** here; this contract authorizes no new dataset, real household consent, trading, cash, Production SQLite, or Business gate admission. No real Keycloak realm has been created/deployed by this PR.

## What is now executable with explicit configuration

`ronas_api.local_keycloak_bff.create_from_environment()` composes the **already implemented** signed Keycloak token verifier, PKCE S256 browser redirect, code exchange against a fixed operator-pinned Realm `/protocol/openid-connect/token`, encrypted SQLite browser-session reference store, and the existing two authenticated UI shells. No fake user is created; the code-exchange requires real Keycloak-issued signed access and ID tokens, matching nonce/subject/audience and the configured public JWKS. Authenticated display is the existing nonoperational user/admin shell. The local transport is mockable for automated tests and otherwise uses TLS-validated HTTP with redirects disabled and no inherited proxy settings.

The opt-in ASGI entrypoint is **`ronas_local_bff:app`**, deliberately separate from default `ronas_api.app:app`. Import fails on missing configuration, invalid Keycloak issuer/public JWKS, unusable 0600 key, or missing private session path; default app continues **not mounting** any browser flow. This is **not** an approved Production entrypoint. Only a loopback HTTPS callback is allowed to avoid accidental public deployment. HTTPS termination and trusted operator-supplied certificates are required; no fake TLS certificates, default users, passwords or secrets have been generated or committed.

Explicit required env keys:
- `RONAS_LOCAL_BFF_ENABLE=LOCAL_TEST_ONLY`, without which the launcher fails to import.
- Existing `RONAS_KEYCLOAK_ISSUER`, `RONAS_KEYCLOAK_API_CLIENT_ID`, `RONAS_KEYCLOAK_BROWSER_CLIENT_ID`, `RONAS_KEYCLOAK_JWKS_FILE` (public version-pinned JWKS verified by the operator).
- `RONAS_LOCAL_BFF_CALLBACK_URL`: exact `https://localhost:PORT/api/auth/callback` or `https://127.0.0.1:PORT/api/auth/callback`, matching authorized Keycloak redirect URI; PORT is chosen by the operator and not assumed here.
- `RONAS_LOCAL_BFF_SESSION_DATABASE`: absolute local SQLite path under a pre-created user-owned private directory; this is **not** Production storage.
- `RONAS_LOCAL_BFF_SESSION_KEY_FILE`: absolute existing user-owned 0600 regular binary file holding exactly 32 random bytes in a private directory; the value must never be stored in source control or shell history.

An operator with a separately approved local HTTPS certificate/server may run an ASGI server bound to **loopback only** against the module `ronas_local_bff:app`. Neither HTTPS certificates, user accounts, secret keys nor a Keycloak deployment are provisioned by Ronas. Session store handles atomic state take, encrypted PKCE/access token/CSRF persistence, expiration and revocation in one host. The BFF never exposes access tokens to the browser, uses Secure/HttpOnly/SameSite cookies, CSRF plus strict Origin for logout, and rejects the second use of callback state.

**Explicitly absent:** Real household/crop/source data, qualified professionals, app-level grant authority, correct public consent/legal terms, data retention policy, distributed/production sessions, automated JWKS remote update, commercial rights, billing, trading, Stage and Production. Existing Business Gate issues #2/#3/#4 stay OPEN, Business PR #1 and Technical PR #9 remain Draft/Open/unmerged. A green test is not owner approval.

## Verification

The new `test_local_keycloak_bff.py` performs signed RSA token + real PKCE HTTP shape (HTTP MockTransport only), login/callback/cookie/server sessions, role-scoped existing UI, no arbitrary finance writes, session encryption, nonce/signature/replay rejection, CSRF/Origin logout, fail-closed strict opt-in/env/callback/keyfile, and default app still not mounting the browser BFF. Full existing Python/Node suites run in CI. No container, internet, actual user accounts or Production credentials are used in tests.
