# روناس | Ronas

محصول پیشنهادی کشاورزی شهری، بازار محلی و زنجیره ارزش صادرات محصولات کشاورزی.

## وضعیت فعلی
- **Business:** دو موتور Domestic و Export هم‌زمان با قراردادها و Business Gate مستقل؛ مستندات هنوز در [PR #1](https://github.com/mahdimarzooghi4-debug/Ronas/pull/1) پیش‌نویس هستند.
- **Technical / Sprint 01:** بسته پیشنهادی API فقط‌خواندنی برای **فهرست قابلیت‌های طراحی‌شده**، همراه با تست و CI، در Draft PR جداگانه و وابسته به شاخه Business.
- **نه یک سامانه تجاری آماده:** هیچ عضویت واقعی، توصیه AI، سفارش، کالا، پرداخت، پردازش مالی، صادرات، کنترل کیفیت عملیاتی یا Production پیاده‌سازی نشده است.

## اجرای محلی نمونه فنی
این API تنها قابلیت‌های پیشنهادی را نشان می‌دهد و داده واقعی کاربر یا تراکنش ندارد.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e './backend[test]'
uvicorn ronas.app:app --reload
# GET http://127.0.0.1:8000/api/v1/product/engines
python -m pytest backend/tests -q
```

## فرآیند مادر
`Business → Technical → Product Backlog → Sprint → Code → Code Review → Stage → QA/Testing → Release Approval → Production → Monitoring → Improvement`

**محدودیت:** وضع کنونی تنها مرحله آزمایشی Code است. موفقیت تست/CI به معنای عبور Business Gate، Stage یا تأیید Release نیست. هیچ PR بدون دستور صریح کارفرما ادغام/منتشر نمی‌شود.
