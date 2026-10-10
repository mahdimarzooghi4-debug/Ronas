# Ronas: signed-token backend foundation

## CURRENT: encrypted local session reference and role-gated two-shell BFF (2026-10-10)

These are tested implementation candidates, not a selected production datastore or live service. The explicit optional BFF serves exactly TWO server-authenticated HTML views: / for Ronas users/partners, /admin for one admin panel whose sections are filtered by signed Keycloak client roles. No customer PII, commercial activity, real login or hosting is activated.

backend/ronas_api/session_sqlite.py is a local/test reference: encrypted AES-256-GCM session and pending PKCE data at rest; SHA-256 lookup digests rather than bearer cookies in SQLite keys; transactional one-time pending-state consumption, multi-connection visibility, time-limited sessions, revocation, and fail-closed decryption. It is NOT the production or distributed session datastore. No default encryption key exists.

backend/ronas_api/ui_bff.py renders only server-authorized synthetic case cards in the two approved shells. Client-side logout script fetches same-origin CSRF and calls server-side revocation without ever holding an access token. The original prototype/ui pages remain independent offline static demonstrations. A missing authorized session cannot render protected cards.

Default app does NOT mount /, /admin, /api/auth/start, /api/auth/logout, or a session store. Only explicit create_app(config, browser_flow) in offline tests mounts these routes. REAL Keycloak and operational multi-replica session storage are not configured. See backend/oidc-browser-contract.md and infra/keycloak/README.md. Business #2/#3/#4 OPEN; PRs Draft/Open/Unmerged, no deployment.

Reproduction: PYTHONPATH=backend python -m unittest discover -s backend/tests -v. All signing and encryption test keys are ephemeral and synthetic.

---

## مصوبه Keycloak و مرز استقرار

کارفرما در 2026-10-10 **Keycloak خودمیزبان** را تصویب کرده است. اجرای پیش‌فرض اکنون فقط KeycloakConfig.from_environment را فعال می‌کند و امضاهای public JWKS و نقش‌های مختص API Client روناس، audience و azp را ارزیابی می‌کند. آداپتر عمومی قبلی AuthConfig صرفاً برای تزریق آزمون‌های ایزوله باقی مانده است و Runtime پیش‌فرض راه میانبر به هویت غیر-Keycloak ندارد. [راهنمای اتصال Keycloak](../infra/keycloak/README.md). هیچ سرور واقعی Keycloak، کاربر یا Client هنوز فراهم نشده است.


Status: **isolated, unadmitted Technical/API candidate** on draft PR #9, not Production or the selected Ronas technology stack. Backend implements real HTTP routing through FastAPI and real signature verification for trusted RS256 JWTs (PyJWT/cryptography). It intentionally exposes **read-only synthetic examples only**, no live household data, approved consent workflow, registration, payment, trading, external provider API or operational database. The old standalone UI demo is separate; opt-in authenticated BFF views are now independently tested.

## Historical generic OIDC adapter (test-only, superseded by approved Keycloak)

The RONAS_OIDC_* settings described in the following historical section are NOT accepted by the default runtime: only RONAS_KEYCLOAK_* provisioned by the trusted operator can configure its protected API.

## Authentication and scope
Requires four explicit runtime values: RONAS_OIDC_ISSUER (exact HTTPS issuer), RONAS_OIDC_AUDIENCE (actual API audience), RONAS_OIDC_KEY_ID (pinned external signer key ID), RONAS_OIDC_PUBLIC_KEY_FILE (absolute path to read-only RSA public-key PEM from that signer). **No values are supplied here, and no real provider has been configured or approved**. Missing/invalid config leaves all protected routes blocked with 503. Liveness GET /healthz does not indicate readiness; GET /readyz checks local public-key configuration only.

A signed Bearer token must have expected RS256 signature, key ID, issuer, audience, expiration, issued-at, not-before and subject plus an issuer-signed array named ronas_roles using the exact approved role vocabulary. Server-side authorization checks each route independently; a finance or governance role cannot access household/export data without its own separate explicit grant. Browser scripts, X-Role headers, unauthenticated JSON and synthetic sessionStorage are **never** role sources. No token minting, test/development login, automatic admin privileges or writable routes exist.

## Read-only endpoints
- GET /api/v1/me — verified subject and roles
- GET /api/v1/domestic/household-intake/example — household role only, always DEMO-H01, unverified consent
- GET /api/v1/admin/domestic/household-intake/example — domestic_ops only, same fake record
- GET /api/v1/admin/export/research/example — export_ops only, DEMO-SOURCE-01 rights unverified, no buyer/contract
- GET /api/v1/admin/finance/status — finance role only, never a transfer
- GET /api/v1/admin/governance/status — governance role only, never an authorization to approve operational records

The remaining external roles local_buyer, agronomy_expert, equipment_seller and export_supplier may read only GET /api/v1/me until explicit Business scope exists. Eliminated portals #6/#8/#9/#13 and API-only logistics #5 are not recreated. UI approval RON-DEC-030/031 is preserved; no cross-engine access inherited from a shared UI.

## Verification
From repo root, Python 3.12 virtualenv:
1. python -m pip install -r backend/requirements-test.txt
2. PYTHONPATH=backend python -m unittest discover -s backend/tests -v
3. PYTHONPATH=backend python -m compileall -q backend/ronas_api

Tests generate ephemeral RSA private keys in process and check signed access tokens, bad claims, tampered keys, role isolation, failure without issuer/key configuration, disabled write routes, and security headers. **Never commit an IdP private key or paste live credentials**.

## Next gates
Production OIDC issuer + controlled role mapping, key rotation/JWKS and revocation policy, live browser PKCE, operational distributed server sessions, global permission revocation, records/tenant-level ownership, consent and data retention, lawful source permissions, observability, Postgres/hosting/NFR/ADR, security testing and human review are **not complete**. A configured RSA public key is NOT evidence of legal data access or deployment readiness. Domestic Gate #2 / Export Gate #3 / Finance Gate #4 stay OPEN; PR #1 and #9 stay Draft/Open/Unmerged. No Stage/QA approval/Release/Production is implied.
