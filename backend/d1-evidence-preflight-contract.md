# روناس — کنترل آفلاین فهرست شواهد آمادگی داده Domestic (D1-DATA-02)

**وضعیت: LOCAL/TEST / سند و قرارداد نامزد / بدون تأیید علمی، حقوقی یا عملیاتی.** مرتبط با [D1-DATA-01](../docs/business/77-core-d1-household-data-consent-contract-candidate.md) و [متن اطلاع‌رسانی پیشنهادی D1-DATA-02](../docs/business/78-core-d1-draft-household-notice-and-input-catalog.md) که **هنوز در PR #1 به‌صورت Draft و بدون پذیرش** هستند.

## چرا این قابلیت لازم است؟

روناس مسئول داخلی آماده‌سازی متن اطلاع‌رسانی، تعریف حداقل اطلاعات خانوار، قرارداد اصلاح/انصراف، صلاحیت کارشناس و مدارک علمی است. ثبت کردن فایل یا یک hash در GitHub هرگز به‌معنی تأیید رضایت صاحب داده، حقوق داده یا دانش علمی نیست. این قرارداد، فقط **جایگاه مدارک تهیه‌شده برای مرور داخلی** و فقدان مدارک دیگر را تفکیک می‌کند. هیچ فرم/فیلد واقعی و هیچ دوره نگهداری را اختراع نمی‌کند.

`backend/ronas_api/d1_data_evidence_preflight.py` یک تابع خالص `evidence_preflight(tuple_of_pointers)` و نوع تغییرناپذیر `InternalEvidencePointer` دارد:

- `D1-DATA-E01..E07` صرفاً **برچسب‌های درخواست شواهد نامزد Business** هستند؛ در `HOUSEHOLD_CULTIVATION_PLAN` و `AI_TRAINING` دو سبد جدا برای **آماده‌سازی** ثبت می‌شوند؛ **۱۴ جایگاه فهرست پیشنهادی هرگز به‌معنی ۱۴ الزام قانونی یا الزام نهایی Business نیست**.
- هر رکورد فقط `DEMO-` reference، شماره نسخه، SHA-256-shaped fingerprint، شناسه شواهد و هدف را ثبت می‌کند؛ **نه محتوای سند یا داده خانوار، نه حقوق استفاده، نه هویت شخص، نه رضایت امضاشده**.
- سند موجود فقط `SUBMITTED_UNVERIFIED` است، نه `APPROVED` یا `VERIFIED`؛ سند ناموجود `MISSING`. رکورد تکراری، شناسه جعلی، نسخه نامعتبر، digest نامعتبر و وضعیت خوداظهاری تأییدشده رد می‌شوند.
- خروجی شامل جایگاه‌های مفقود، نسخه‌های پیش‌نویس و اثرانگشت تکرارپذیر کل فهرست است؛ **digest تک‌سند منتشر نمی‌شود**.
- تمامی اختیارها و شواهد تأیید (`source_rights_verified`, `service_purpose_consent_verified`, `training_purpose_rights_verified`, `expert_qualification_verified`, `scientific_quality_verified`, `allow_real_household_data_ingest`, `allow_household_plan_ai`, `allow_ai_training`, `allow_specialist_plan_approval`, `business_gate_2_passed`, `stage_or_production_admitted`, …) **همیشه false** هستند، حتی اگر همه جایگاه‌های نامزد پر شده باشند.

## چه‌چیزی عمداً ایجاد نشده؟

هیچ رکورد رضایت، تصمیم قبول/رد حقوق، احراز قضایی/قانونی، قرارداد نگهداری یا Withdrawal، ثبت داده واقعی، پرونده واقعی خانوار، اجرای مدل/Training، پذیرش برنامه یا Stage/Production ساخته نشده است. هیچ API، صفحه عملیاتی، نوشتن به پایگاه داده و endpoint اجازه صادرکننده نیز ایجاد نشده است. این فهرست با داده مصنوعی در آزمون‌ها اجرا می‌شود؛ برای تغییر آن به مسیر واقعی باید ابتدا قرارداد Business، حقوق واقعی، مرجع تأیید مستقل و فرایند Technical/Gate رسماً تعیین شوند.

## نمونه استفاده فقط در تست

```python
from ronas_api.d1_data_evidence_preflight import (
    InternalEvidencePointer, evidence_preflight,
)

candidate = InternalEvidencePointer(
    evidence_id="D1-DATA-E01",
    document_ref="DEMO-NOTICE-REVIEW",
    version=1,
    manifest_sha256="1" * 64,
    purpose="HOUSEHOLD_CULTIVATION_PLAN",
)
report = evidence_preflight((candidate,))
assert report["provided_pointer_count"] == 1
assert report["allow_real_household_data_ingest"] is False
assert report["allow_ai_training"] is False
```

**آزمون‌های بازدارنده:** `backend/tests/test_d1_data_evidence_preflight.py`. گیت Domestic #2، Export #3 و Finance #4 باز؛ PR #1 و #9 Draft/Open/Unmerged؛ هیچ Ready for Review، Merge، Stage، QA، Release یا Production مجاز نشده است.
