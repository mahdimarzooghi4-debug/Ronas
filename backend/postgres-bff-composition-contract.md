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


The browser session store also provides a shared per-session refresh lease. The
lease serializes Keycloak refresh grants across API instances and is cleared in
the same database transaction that replaces the encrypted session payload.

The LOCAL/TEST factory can also receive an already configured
`PostgresHouseholdProgressNoteLedger` as `household_progress_note_ledger`. The
factory accepts it only when it is bound to the exact shared synthetic
household case ledger, schema reference, and owner-access authority, then passes
it through to the household API and shared-user workspace. This keeps private
progress history in its encrypted PostgreSQL journal across BFF instances;
omitting it preserves the existing synthetic SQLite journal behavior. This
does not enable real household data or a production deployment.

Service-backed CI also exercises the full synthetic browser round trip: a
Keycloak PKCE login on one BFF, an owner-only CSRF/Origin-protected progress
note submission through the Persian household form on another BFF, and history
readback through the first BFF. Each instance constructs its own journal
adapter with the same test keys; PostgreSQL is the shared persistence boundary.
The test verifies that the event log records append/read events and that stored
note ciphertext does not contain the submitted text.
