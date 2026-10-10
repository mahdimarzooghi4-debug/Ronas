# Ronas: signed-token backend foundation

## جزئیات پرونده خانوار و پیگیری وضعیت فنی — فقط LOCAL/TEST

قابلیت بعدی «پرونده‌های من» در همان محیط مشترک کاربران توسعه یافت: با دفتر بررسی فنی تزریق‌شده و نشست Keycloak معتبر، خانوار می‌تواند صفحه `/my-drafts/{ref}` را برای پرونده Domestic متعلق به خودش ببیند. مسیر JSON خواندنی `/api/v1/domestic/household-intake/my-drafts/{ref}/technical-status` فقط **وضعیت فنی مشاهده‌شده** و نسخه را نشان می‌دهد؛ متن شواهد، مرجع پاسخ، شناسه بازبین یا تأیید Business را افشا نمی‌کند. همه پرونده‌ها `DRAFT_ONLY` هستند و حتی `HUMAN_RESPONSE_RECORDED` تأیید طرح کشت نیست.

این نما فقط با نمونه مشترک `SqliteSyntheticHumanReviewLedger`، احراز هویت امضاشده و مجوز مالک دقیق پرونده فعال است؛ اجرای پیش‌فرض و دیتابیس SQLite معمولی بدون تاریخچه بررسی آن را فعال نمی‌کنند. دسترسی اشتباه `404`، خطای دفتر `503`، و نشست نامعتبر `401` می‌گیرد. **هیچ دکمه ثبت، ویرایش یا تأیید وجود ندارد.** قرارداد کامل: [scoped-records-contract.md](scoped-records-contract.md). آزمون: `backend/tests/test_owned_household_technical_status.py` (۱۳ سناریو).


## پرونده‌های من — محیط مشترک کاربران (فقط LOCAL/TEST)

در همان محیط کاربران و همکاران `/`، خانوار دارای نشست معتبر Keycloak می‌تواند فهرست تغییرناپذیر پرونده‌های **Domestic متعلق به شناسه امضاشده خودش** را ببیند. مسیر GET آزمایشی `/api/v1/domestic/household-intake/my-drafts` دارای صفحه‌بندی و ممیزی تراکنشی است؛ فقط با تزریق صریح `SqliteSyntheticGrantLedger` فعال می‌شود. کاربران دیگر، کارشناسان، خریداران و کارکنان داخلی از صرف نقششان به پرونده خانوار دسترسی ندارند. داده‌ها DEMO هستند؛ وضعیت تمام پرونده‌ها `DRAFT_ONLY` و وضعیت رضایت و تأیید متخصص منفی/تأییدنشده می‌ماند. هیچ ثبت، ویرایش، پذیرش، فروش یا پرداختی فعال نیست.

کد: `ronas_api/owner_case_api.py`، `ronas_api/grant_ledger_sqlite.py` و `ronas_api/ui_bff.py`. قرارداد کامل در [scoped-records-contract.md](scoped-records-contract.md) و ۱۵ آزمون در `backend/tests/test_owned_household_drafts.py` است. این قابلیت پایه‌ای برای توسعه آینده محیط مشترک است، نه مجوز استفاده از داده شخصی، اتصال واقعی Keycloak یا عبور از Gateهای Business.


## فهرست فنی بررسی شواهد برای اپراتور مجاز — فقط LOCAL/TEST

قابلیت کاربردی جدید در `human_review_sqlite.py`، `technical_review_api.py` و `ui_bff.py` پیاده شده است: فهرست صفحه‌بندی‌شده فقط از **پرونده‌های ساختگی تخصیص‌یافته با مجوز فعال**، همراه با نسخه پرونده، وضعیت فنی بررسی و وضعیت ثابت `DRAFT_ONLY`. یک تراکنش واحد بررسی مجوز و ممیزی نمایش هر ردیف را انجام می‌دهد؛ لغو مجوز، آن پرونده را از فهرست بعدی حذف می‌کند. Domestic و Export مستقل هستند؛ Finance و Governance از روی نقش خود به پرونده‌ها دسترسی پیدا نمی‌کنند.

این فهرست در دو مسیر GET آزمایشی `/api/v1/admin/domestic/household-intake/technical-review-worklist` و `/api/v1/admin/export/research/technical-review-worklist` و در **همان صفحه /admin موجود** قابل مشاهده است؛ مشروط به تزریق صریح یک نمونه مشترک از دفتر مجوز/بررسی و نشست مرورگر معتبر Keycloak. اجرای پیش‌فرض این مسیرها و رابط را فعال نمی‌کند. فهرست یک صف تصمیم‌گیری Business، مجوز بررسی کارشناسی، تأیید طرح کشت یا تعیین حقوق منبع صادرات نیست؛ هیچ endpoint تأیید یا پرونده واقعی ساخته نشده است.

قرارداد: [technical-human-review-contract.md](technical-human-review-contract.md). آزمون‌ها: `backend/tests/test_technical_review_worklist.py` شامل ۱۸ سناریوی API و صفحه مدیریت؛ CI باید برای HEAD همین PR سبز باشد.


## تاریخچه ثبت درخواست بررسی و پاسخ انسانی — فقط نمونه فنی

ماژول human_review_sqlite.py و قرارداد technical-human-review-contract.md گردش دو مرحله‌ای درخواست بررسی شواهد و ثبت مرجع پاسخ انسانی را با تأیید اختیار مستقل بازبین، کنترل نسخه، ثبت اتمیک و آزمون‌های امنیتی پیاده کرده‌اند. **وضعیت Business پرونده همواره DRAFT_ONLY باقی می‌ماند.** هیچ تأیید طرح کشت، حقوق منبع صادرات، داده واقعی یا API عمومی تصمیم انسانی در این مرحله فعال نشده است.


## دفتر آزمایشی پایدار لغو مجوز (2026-10-10)

[قرارداد SQLite و بازیابی](grant-ledger-sqlite-contract.md) و [کد ثبت تراکنشی](ronas_api/grant_ledger_sqlite.py) اضافه شد. رویداد ممیزی و لغو مجوز پرونده ساختگی به‌صورت اتمیک ذخیره می‌شوند و پس از بازگشایی SQLite اعتبارسنجی می‌گردند؛ هم‌زمانی، اجرای تکراری و خرابی تاریخچه رد می‌شوند. **این ابزار آزمون محلی تک‌میزبان است، نه پایگاه داده یا دفتر ممیزی Production**؛ در اجرای پیش‌فرض فعال نیست.


## تاریخچه نسخه و ممیزی لغو مجوز پرونده — نمونه فنی

[قرارداد audit و revocation](scoped-audit-contract.md) و ماژول [scoped_audit.py](ronas_api/scoped_audit.py) به نمونه‌های ساختگی اضافه شد. تاریخچه فقط نسخه‌های تغییرناپذیر *از قبل تعریف‌شده* را نشان می‌دهد؛ ممیزی خواندن و لغو دسترسی صرفاً در حافظه فرایند به صورت زنجیره هش نگهداری می‌شود، نه در لاگ مستقل یا دیتابیس Production. لغو فقط با callback اختیارات مستقلِ تزریق‌شده به کد (بدون endpoint عمومی) و کنترل نسخه انجام می‌شود؛ توکن معتبر Keycloak پس از لغو نیز مجوز پرونده را بازنمی‌گرداند. **این قرارداد هیچ مرجع واقعی اختیار و هیچ سیاست نگهداری داده یا مجوز بهره‌برداری تأییدشده‌ای نمی‌سازد.**


## محدوده دسترسی هر پرونده (نمونه، 2026-10-10)

[قرارداد پرونده‌های سطح رکورد](scoped-records-contract.md) و ماژول scoped_drafts.py اضافه شده‌اند. کارشناس Domestic یا Export حتی با نقش امضاشده Keycloak فقط پرونده ساختگی‌ای را می‌خواند که صریحاً به شناسه وی تخصیص داده شده باشد؛ خانوار تنها پرونده خود را می‌خواند. داده واقعی، تأیید و تراکنش نداریم؛ مسیرهای جدید در اجرای پیش‌فرض غیرفعال هستند.


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
