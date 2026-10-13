# Keycloak RP-Initiated Logout contract

The LOCAL/TEST browser app offers two logout routes:

- `POST /api/auth/logout` closes the Ronas browser session locally.
- `POST /api/auth/logout/keycloak` first closes the local session, then redirects the browser to the Keycloak OpenID Connect logout endpoint.

The second route is the user-facing browser logout. It requires the current Ronas session, the exact same-origin `Origin`, and a CSRF value. The BFF verifies the signed access token before this action. It then revokes the session before redirecting, so a provider outage or user cancellation does not reopen the Ronas session.

The BFF retains the signed ID token only inside the encrypted server-side session store. The user session endpoint never returns it. On explicit logout, the BFF sends it as `id_token_hint` together with the pinned browser `client_id`, the fixed `post_logout_redirect_uri`, and a random `state`. The callback accepts only a constant-time match against a Secure, HttpOnly, host-only state cookie; successful callback consumes that cookie and returns to `/`. No client-controlled redirect is accepted.

Keycloak's browser client must register the exact callback URI:

`{RONAS_LOCAL_BFF_CALLBACK_URL_ORIGIN}/api/auth/logout/callback`

The URI uses the same HTTPS loopback origin as the explicitly enabled LOCAL/TEST BFF. For any future hosted environment, the exact HTTPS URI must be registered in Keycloak before that environment can use this flow. No wildcard URI is supported.

Tests use synthetic signed tokens and a mock Keycloak token endpoint. They verify local revocation before provider redirect, CSRF and Origin checks, state mismatch and callback replay rejection, and persistence of the ID token only inside encrypted session adapters. The tests do not connect to a live Keycloak realm or approve a hosted redirect URI.
