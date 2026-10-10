# روناس | Ronas

اکوسیستم پیشنهادی کشاورزی شهری، بازار محلی و توسعه زنجیره ارزش صادراتی محصولات کشاورزی.

## وضعیت پروژه

- **مرحله:** Business Foundation — در حال تدوین و بازبینی
- **منبع پایه:** «طرح نامه جامع روناس»، مرداد ۱۴۰۵، سفارش معاونت اشتغال کمیته امداد امام خمینی(ره)، طراحی خانه خلاق و نوآوری آینه (سند مبنا در اختیار کارفرما)
- **تصمیم راهبردی تأییدشده:** طراحی هم‌زمان **دو موتور مستقل بازار داخلی و صادرات**، با قراردادها، مدل اقتصادی، ریسک‌ها و مسیر تحقق جداگانه.
- **وضعیت پیاده‌سازی:** هنوز کد محصول، معماری مصوب، استقرار یا خدمات عملیاتی وجود ندارد.
- **Business v0.38 (2026-10-10):** جهت‌گیری‌های RON-DEC-022..025، آماده‌سازی موازی D0/E0 طبق RON-DEC-026 و **سیاست هوش کاملاً داخلی روناس طبق RON-DEC-027** تصویب شده‌اند؛ این تصویب‌ها هیچ گیت اجرایی را عبور نمی‌دهند.
- **تمرکز فعلی روی محصول اصلی:** [مسیر بحرانی Domestic / Export / Finance](docs/business/72-core-delivery-critical-path-and-business-gate-readiness.md)؛ [خانوار تا برداشت و مازاد](docs/business/70-core-domestic-operational-scope-and-business-acceptance.md) و [فرصت صادرات تا قرارداد](docs/business/71-core-export-operational-contract-and-readiness.md) در سطح **نامزد قرارداد Business** آماده‌اند. هنوز Gate PASS یا مجوز کدنویسی نیستند؛ جزئیات Training AI فعلاً اولویت کار اصلی نیست.
- **هوش روناس:** [سیاست مصوب Business: Dataset اولیه دارای حق استفاده، یادگیری/بازآموزی نسخه‌دار و ارتقای انسانی](docs/business/64-ronas-internal-ai-progressive-learning-business-direction.md). **طبق RON-DEC-028، مسیر مدل پایه Open-Weight دارای مجوز معتبر با Fine-tuning و اجرای کاملاً داخلی تصویب شده**؛ مدل/نسخه/مجوز مشخص، حقوق Training، دیتاست اولیه و طراحی فنی هنوز انتخاب/تأیید نشده‌اند. هیچ مدل یا دیتاست Training واقعی ساخته نشده است. [نقشه شواهد](docs/business/65-initial-ai-dataset-and-controlled-learning-evidence-blueprint.md).
- **بررسی نامزد مدل (Business / غیرمصوب):** [مقایسه Gemma 4، Qwen3.5 و Qwen3](docs/business/66-open-weight-base-model-candidate-screening.md) فقط ثبت منابع رسمی و شکاف‌های حقوق/ارزیابی است؛ هنوز مدل روناس انتخاب نشده.
- **روش ساخت هوش — RON-DEC-028:** انتخاب **گزینه ب** در سطح Business است، نه مجوز ورود به Technical، دانلود وزن، آموزش، کدنویسی یا استقرار.
- **ترتیب آماده‌سازی هوش — RON-DEC-029:** [D0 ابتدا برای شواهد Business و E0 موازی و مستقل](docs/business/69-d0-first-evidence-execution-plan-e0-parallel.md) تصویب شده؛ **نه نخستین Task واقعی Training یا Dataset**. گیت Technical و Code هنوز بسته‌اند.
- **گیت‌ها:** [Domestic #2](https://github.com/mahdimarzooghi4-debug/Ronas/issues/2)، [Export #3](https://github.com/mahdimarzooghi4-debug/Ronas/issues/3) و [Finance #4](https://github.com/mahdimarzooghi4-debug/Ronas/issues/4) **OPEN**؛ [PR #1](https://github.com/mahdimarzooghi4-debug/Ronas/pull/1) Draft/Unmerged، [PR #6](https://github.com/mahdimarzooghi4-debug/Ronas/pull/6) HOLD، [PR #8](https://github.com/mahdimarzooghi4-debug/Ronas/pull/8) Discovery-only.

## شیوه کار

چارچوب اجرای محصول:
`Business → Technical → Scrum/Product Backlog → Sprint → Code → Code Review → Stage → QA/Testing → Release Approval → Production → Monitoring → Improvement`

مستندات فاز Business در شاخه `business/ronas-foundation-v0-1` و Draft PR تدوین می‌شوند. تا تصویب قراردادهای مرتبط، از فرض‌کردن درصد کارمزد، سیاست تسویه، تضمین کیفیت، خرید قطعی محصول، صلاحیت تولیدکننده، الگوریتم هوش مصنوعی یا استانداردهای صادراتی خودداری می‌شود.

> این مخزن در حال حاضر محل طراحی و توسعه است؛ هیچ جریان پرداخت واقعی، معاملات عملیاتی، مدل AI مستقر یا قابلیت صادرات فعال نشده است.
