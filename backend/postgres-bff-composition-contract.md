# PostgreSQL-backed LOCAL/TEST BFF composition

```python
from ronas_api.local_keycloak_bff import (
    PostgresLocalBFFSettings,
    create_postgres_local_test_bff,
)

settings = PostgresLocalBFFSettings.from_environment()
app = create_postgres_local_test_bff(settings)
```

This opt-in composition connects the existing Keycloak Authorization Code + PKCE
browser flow to the encrypted PostgreSQL implementation of
`BrowserSessionStore`. A pending login created on one API instance can be
consumed on another, and the resulting opaque browser session can be read from
either instance. The callback state remains single-use across instances.

Required environment inputs:

- `RONAS_LOCAL_BFF_ENABLE=LOCAL_TEST_ONLY`
- `RONAS_LOCAL_BFF_CALLBACK_URL` using loopback HTTPS and the fixed callback path
- `RONAS_LOCAL_BFF_POSTGRES_DSN`
- `RONAS_LOCAL_BFF_SESSION_KEY_FILE` pointing to a private 32-byte AES key file
- Existing operator-pinned Keycloak issuer, clients, and JWKS configuration

The factory explicitly constructs the PostgreSQL session adapter and fails
closed if configuration or database initialization fails. It does not activate
the default application, create a deployment entrypoint, provision Keycloak,
or make synthetic case records operational. The SQLite LOCAL/TEST composition
continues to use its existing factory. Both compositions use the same
server-side OIDC flow and route authorization.

The integration test uses the CI PostgreSQL service and mock Keycloak HTTP
transport with locally signed synthetic tokens. It checks cross-instance
callback consumption, session access, token confinement to the server, and
callback replay rejection. It does not exercise a live browser, hosted identity
provider, multi-region database, operational key rotation, backups, or
Production acceptance.
