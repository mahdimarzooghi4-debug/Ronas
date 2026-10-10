# روناس — Keycloak خودمیزبان: راهنمای واقعی اتصال

**تصمیم صاحب محصول (2026-10-10):** Keycloak خودمیزبان برای احراز هویت انتخاب شد. در این شاخه پیاده‌سازی backend برای توکن‌های Keycloak انجام شده است؛ **استقرار Keycloak، ساخت Realm، Client، کاربر و اتصال به هویت واقعی هنوز انجام نشده**.

## قرارداد الزامی Realm / OIDC

1. یک Keycloak خودمیزبان با PostgreSQL پایدار، DNS و TLS/HTTPS واقعی نیاز داریم. دقیقاً یک Issuer برای Realm روناس به شکل نمونه https://HOST/realms/REALM (HOST و REALM واقعی هنوز انتخاب نشده‌اند).
2. در Realm دو Client مستقل تعریف شوند: **Browser Client عمومی** با Authorization Code + PKCE S256 (بدون Direct Access Grant و Implicit) و **API Client** برای سرویس روناس. Redirect URI و Web Origin مرورگر باید دقیقاً محدود به دامنه مصوب باشد، نه wildcard.
3. Audience Mapper / Audience Resolve باید شناسه API Client را به audience توکن دسترسی بیفزاید. کلاینت مرورگر باید در ادعای امضاشده azp قرار بگیرد. API فقط access token با ادعای typ=Bearer قبول می‌کند؛ ID token جایگزین نیست.
4. **نقش‌ها فقط Client Roleهای API** و در فیلد امضاشده resource_access[API_CLIENT_ID].roles هستند؛ Realm roles، نقش‌های Client account، X-Role و منوی UI هیچ حق مستقلی ایجاد نمی‌کنند.
5. تنها نقش‌های مجاز: household, local_buyer, agronomy_expert, equipment_seller, export_supplier, domestic_ops, export_ops, finance, governance. یک پنل مدیریت با چهار ناحیه مجوز جدا، بدون Super Admin خودکار.
6. هر تغییر Client Role به تأیید مسئول هویت نیاز دارد. فرآیند ابطال، نقش‌های هر پرونده، دسترسی شراکت، احراز هویت چندعاملی و بازبینی حق دسترسی هنوز باید در محیط واقعی تعیین و آزموده شوند.

## کلید عمومی، اعتبارسنجی و چرخش

Discovery رسمی Realm: https://HOST/realms/REALM/.well-known/openid-configuration

JWKS رسمی Realm: https://HOST/realms/REALM/protocol/openid-connect/certs

اپراتور مجاز باید کلیدهای عمومی امضای RS256 را از HTTPS واقعی همان Realm دریافت/تأیید کند و JWKS عمومی را در **فایل نسخه‌دار، فقط‌خواندنی و تحت کنترل زیرساخت** در اختیار API قرار دهد. فایل نباید هیچ کلید خصوصی داشته باشد. اپلیکیشن از URL دلخواه موجود در Header توکن کلید دانلود نمی‌کند. برای چرخش کنترل‌شده، نسخه فایل JWKS شامل کلید امضای قدیم و جدیدِ تأییدشده آماده و به صورت اتمیک نصب شود و API مجدداً راه‌اندازی/تست گردد؛ دانلود و refresh خودکار کلید در این مرحله پیاده‌سازی نشده است. کلید ناشناخته رد می‌شود.

| Environment Key | داده‌ای که اپراتور باید از محیط واقعی بیاورد |
| --- | --- |
| RONAS_KEYCLOAK_ISSUER | URL دقیق HTTPS مربوط به Realm |
| RONAS_KEYCLOAK_API_CLIENT_ID | شناسه Client منطقی API |
| RONAS_KEYCLOAK_BROWSER_CLIENT_ID | شناسه Client عمومی و مجاز مرورگر |
| RONAS_KEYCLOAK_JWKS_FILE | مسیر **مطلق** فایل عمومی JWKS مورد اعتماد |

هر مقدار ناقص، کلید نامعتبر یا تنظیم اشتباه باعث بسته‌ماندن مسیرهای محافظت‌شده می‌شود (HTTP 503). healthz فقط زنده بودن فرایند است؛ readyz با تنظیمات بارگذاری‌شده **به معنای آمادگی Production نیست**. تنظیمات عمومی RONAS_OIDC قبلی دیگر در Runtime پیش‌فرض Keycloak را دور نمی‌زنند.

## آزمون و راه‌اندازی آفلاین

از ریشه مخزن و محیط مجازی Python 3.12:
- python -m pip install -r backend/requirements-test.txt
- PYTHONPATH=backend python -m unittest discover -s backend/tests -v
- PYTHONPATH=backend python -m compileall -q backend/ronas_api

تست‌ها کلیدهای RSA آزمایشی و موقت در حافظه تولید می‌کنند؛ امضا، نقش Client، جدایی موتور، azp/audience، انقضا، جعل نقش Realm، کلید تقلبی، چرخش کلید، رد JWK خصوصی و عدم وجود مسیرهای نوشتن را بررسی می‌کنند.

## نیازهای بیرونی برای اتصال و استقرار واقعی

- انتخاب میزبان Keycloak و Postgres (ماشین/Container یا محیط ابری مورد تأیید)، دامنه، TLS، DNS، نسخه Container پین‌شده و برنامه Update/Patch؛ از این اطلاعات نمی‌توان خودسرانه مقدار ساخت
- مدیریت امن Bootstrap Admin/MFA، Secrets، Backup/Restore، Monitoring، محدودیت شبکه و Reverse Proxy
- ساخت Realm، API و Browser Client واقعی و اختصاص دادن نقش‌ها با اختیار مدیر شناخته‌شده
- فرآیند ورود OIDC PKCE به محیط «روناس»، مدیریت Session/Logout/Revocation و کنترل CSRF/Cookie/HTTPS
- گیت مجوز داده خانوار، حقوق منابع صادراتی، مالک/صلاحیت بازبین، ذخیره‌سازی و سیاست حذف داده: انتخاب Keycloak به‌تنهایی این مجوزها را تأمین نمی‌کند

**این PR هیچ سرور Keycloak ایجاد یا مستقر نکرده، رمز، کلید خصوصی، دامنه/سرویس/Provider ساختگی ثبت نکرده است.** تصمیم انتخاب محصول هویت پذیرفته شده اما مستلزم استقرار واقعی مجزا است. Business Gateهای Domestic #2، Export #3 و Finance #4 هنوز بازند و PR #1/#9 Draft/Open/Unmerged می‌مانند.

منبع قرارداد OIDC: https://www.keycloak.org/docs/latest/server_admin/ و https://github.com/keycloak/keycloak/blob/main/docs/guides/securing-apps/partials/oidc/available-endpoints.adoc
