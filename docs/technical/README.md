# Ronas — Technical Discovery قبل از پذیرش فنی

**STATUS: PRE-ADMISSION / DRAFT / NOT AN APPROVED ARCHITECTURE OR TECHNOLOGY STACK.**

این بسته در پاسخ به درخواست کارفرما «خب یه چک کنیم بعد بریم سراغ ساختار تکنیکال» پس از [گزارش بررسی Business](../business/51-integrated-business-review-findings.md) تهیه شده است. نتیجه چک Business **یافته‌های مسدودکننده و گیت‌های OPEN** است؛ بنابراین خروجی حاضر فقط **ساختار اکتشافی و گزینه‌های Technical** است، نه `Technical Contract` مصوب، Sprint، API یا کد.

## ترتیب مطالعه
1. [مرز مجوز و مدرک مبنا](00-discovery-charter-and-admission-boundary.md).
2. [نقشه مسئولیت‌های منطقی و مرز Contextها](01-candidate-contexts-and-interactions.md).
3. [داده، امنیت، شواهد و اتصالات بیرونی](02-data-trust-and-integration-questions.md).
4. [گزینه‌های معماری و پرونده تصمیم فناوری](03-architecture-options-and-adrs.md).
5. [ماتریس پیش‌نیاز تبدیل ساختار به قرارداد فنی](04-business-to-technical-admission-matrix.md).

**مرجع تصمیم مصوب:** RON-DEC-001 (استقلال دو موتور)، RON-DEC-003 (چندمدلی با قرارداد Export مستقل، فقط در سطح جهت‌گیری)، RON-DEC-007 (فرآیند مادر توسعه)، RON-DEC-008 (ساختار، سپس چک). PR #6 نمونه اکتشافی Python/FastAPI است و در **HOLD** می‌ماند؛ از آن نه Stack، نه مدل API و نه الگوریتم استخراج نمی‌کنیم.

**منع‌ها:** انتخاب Python/TypeScript/.NET/Go یا DB؛ قطعی‌کردن Microservices/Monolith؛ طراحی عملیاتی API/DB/schema/event؛ فعال‌سازی بانک، مدل AI، معاملات/QC/صادرات؛ ایجاد کد یا CI ادعایی؛ Merge/Stage/Production. همه این تصمیم‌ها به Business Gate و سپس Technical Approval مناسب نیاز دارند.
