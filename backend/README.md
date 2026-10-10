# Ronas: signed-token backend foundation

## مصوبه Keycloak و مرز استقرار

کارفرما در 2026-10-10 **Keycloak خودمیزبان** را تصویب کرده است. اجرای پیش‌فرض اکنون فقط KeycloakConfig.from_environment را فعال می‌کند و امضاهای public JWKS و نقش‌های مختص API Client روناس، audience و azp را ارزیابی می‌کند. آداپتر عمومی قبلی AuthConfig صرفاً برای تزریق آزمون‌های ایزوله باقی مانده است و Runtime پیش‌فرض راه میانبر به هویت غیر-Keycloak ندارد. [راهنمای اتصال Keycloak](../infra/keycloak/README.md). هیچ سرور واقعی Keycloak، کاربر یا Client هنوز فراهم نشده است.


Status: **isolated, unadmitted Technical/API candidate** on draft PR #9, not Production or the selected Ronas technology stack. Backend implements real HTTP routing through FastAPI and real signature verification for trusted RS256 JWTs (PyJWT/cryptography). It intentionally exposes **read-only synthetic examples only**, no live household data, approved consent workflow, registration, payment, trading, external provider API or database. The UI demonstration is not connected.

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
Production OIDC issuer + controlled role mapping, key rotation/JWKS and revocation policy, browser PKCE, authenticated server sessions, permission revocation, records/tenant-level ownership, consent and data retention, lawful source permissions, observability, Postgres/hosting/NFR/ADR, security testing and human review are **not complete**. A configured RSA public key is NOT evidence of legal data access or deployment readiness. Domestic Gate #2 / Export Gate #3 / Finance Gate #4 stay OPEN; PR #1 and #9 stay Draft/Open/Unmerged. No Stage/QA approval/Release/Production is implied.
