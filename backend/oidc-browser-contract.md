# Keycloak browser sign-in (code complete as an opt-in backend contract)

Scope: **Authorization Code + PKCE S256** for the already-approved two-shell Ronas experience. This is a code-and-test deliverable; no hosting, database or live Keycloak connection is required for the automated tests.

The new modules `ronas_api/oidc_browser.py` and `ronas_api/keycloak_exchange.py` implement:
- A fixed Keycloak authorization URL with cryptographically random state, nonce and PKCE verifier.
- One-use callback state with a 300-second maximum pending age, a matching secure HttpOnly SameSite=Lax cookie, and code exchange only after atomic state consumption.
- Fixed HTTPS Token Endpoint POST with grant_type=authorization_code, browser client ID, identical callback URI and the original PKCE verifier; redirects and malformed responses are rejected; refresh tokens are **not stored**.
- RS256 verification of **both** Keycloak-signed access and ID tokens, ID nonce and subject matching, exact browser audience, API-client audience/roles, and bounded signed token lifetime.
- Random opaque session ID in a Secure HttpOnly SameSite=Lax cookie, bearer token held **only server-side** by an injected store; scoped read API routes check that session on each request. Logout requires an exact Origin and CSRF header, and revokes the session in that store.
- No login password handled by Ronas. No Implicit Flow, Direct Grant, ID-token-as-access-token, role inferred from browser UI, or automatic elevation.

**Production fail-closed boundary:** `create_app(KeycloakConfig.from_environment())` does **not** mount these optional browser routes. For code-level integration tests only, `create_app(config, browser_flow)` accepts an explicitly provided `BrowserOIDC` with a trusted operator-managed Keycloak config, an atomic `BrowserSessionStore` and a `CodeExchanger`. The tests use a fake in-memory store and fake signed tokens. The repository now contains an encrypted, transactional, single-host SQLite local/test session adapter, but still does NOT have an approved production/distributed session service, real provider configuration, actual Keycloak enrollment, global revocation or deployed integration. Never instantiate the test store for real users; deployment requires a reviewed persistent, expiring, atomic session provider and a real OIDC administrator.

The adapter `KeycloakCodeExchanger` may be used by the future bootstrap, with an explicitly owned `httpx.AsyncClient` limited to the configured Keycloak HTTPS issuer. Its construction alone never sends a request. Two opt-in server-side role-gated HTML views for / and /admin now exist in the new ui_bff.py module; default runtime mounts neither. They reuse the visual CSS and show only synthetic records. The older prototype/ui pages remain disconnected local demonstrations.

Tests: `PYTHONPATH=backend python -m unittest discover -s backend/tests -v` and the existing CI suite. No secret, purchased resource or actual Keycloak account is needed.

This slice contains a local encrypted session adapter and optional same-origin server-side role-gated HTML UI. Next iteration: determine/implement an independently-reviewed distributed operational session architecture when needed, with explicit deployment approval. This document authorizes neither Stage nor Production.
