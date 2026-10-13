# PostgreSQL Browser Session Store

## Purpose

PostgresBrowserSessionStore implements the BrowserSessionStore protocol used by the Keycloak Authorization Code + PKCE BFF. Multiple API workers can share pending login state and browser sessions in PostgreSQL.

## Stored data and security

- The caller supplies the PostgreSQL DSN and a 32-byte AES-256 key. The default app does not select a DSN, key, or session store.
- The store persists SHA-256 digests for opaque session IDs and OIDC state values. It encrypts the PKCE verifier, nonce, subject, roles, access token, and CSRF value with AES-GCM, binding ciphertext to its purpose and row digest.
- Session identifiers and OIDC state are not stored in plaintext. Expiry timestamps and digests remain available for lookup and cleanup.
- SQL parameters are bound through Psycopg. DSNs and token values are not logged or included in returned errors.
- The adapter does not configure Keycloak, decide role mapping, or revoke tokens at the identity provider.

## Concurrency and expiry

- Pending login state is consumed with one DELETE ... RETURNING statement, so only one worker can exchange a callback state.
- Independent store instances share session reads and revocation.
- Existing BFF lifetimes remain unchanged: pending state expires after 300 seconds and browser sessions after at most 900 seconds.
- purge_expired() is explicit maintenance; scheduling and retention remain caller-owned.

## Test coverage

GitHub Actions starts a PostgreSQL 17 service for the backend suite. Integration tests cover cross-worker one-time consumption, encrypted-at-rest values, duplicate rejection, session revocation, expiry, ciphertext tampering, and cleanup.

## Activation boundary

The adapter is opt-in and can be passed to BrowserOIDC through the existing store protocol. SQLite remains the local reference adapter. This package does not alter production wiring, authorize deployment, or establish operational key rotation, backup, or retention policies.
