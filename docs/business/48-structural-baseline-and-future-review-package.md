# روناس — بسته تحویل ساختار Business و مبنای مرور نهایی آینده | Structural Draft v0.16

**Status:** READING/HANDOFF PACKAGE PREPARED / **FINAL REVIEW NOT STARTED** / BUSINESS GATES STILL OPEN.  
**Authority:** RON-DEC-001 دو موتور مستقل؛ RON-DEC-003 جهت‌گیری قراردادهای مستقل Export؛ RON-DEC-007 ترتیب اجرای محصول؛ RON-DEC-008 تکمیل ساختار، بعداً چک نهایی. هیچ تصمیم محصولی تازه در این سند تصویب نشده است.  
**Privacy:** اصل `طرح نامه جامع روناس.docx` خصوصی می‌ماند و در Public GitHub منتشر نمی‌شود. شناسه‌ها/ارجاعات زیر محل مطالعه‌اند، نه الحاق کل فایل محرمانه.

## ۱. بسته اصلی خواندن — بدون مرور ده‌ها سند به ترتیب تاریخ

| مرحله مطالعه پس از دستور بررسی | مرجع اصلی | آنچه باید در آینده بررسی شود |
| --- | --- | --- |
| A — تصویر کلان | [۴۶ — Atlas](46-integrated-business-structure-atlas.md) | دو موتور و توانمندسازها، ۱۹ جریان، نبود موتور سوم |
| B — سؤالات پاسخ‌نداده | [۴۷ — Gap Register](47-open-structure-gaps-and-evidence-register.md) | همه RON-OPEN و FIN با شواهد/سند مربوط |
| C — منشأ و استقلال | [۰۵ — Source Trace](05-source-traceability-and-exit-gate.md)، [۰۴ — Decisions](04-decisions-and-open-questions.md)، [۰۸ — Boundaries](08-cross-engine-boundaries-and-control-points.md) | SOURCE، APPROVED، OPEN، تضاد و تفکیک دو موتور |
| D — جزئیات Domestic | [۰۱](01-domestic-engine.md)، [۰۶](06-domestic-decision-package.md)، [۲۱](21-domestic-service-blueprints.md) | نقش/عرضه سالم/هاب/قرارداد داخلی |
| E — جزئیات Export | [۰۲](02-export-engine.md)، [۰۷](07-export-decision-package.md)، [۱۱–۱۳](11-export-multicontract-direction.md)، [۲۲](22-export-service-blueprints.md) | محصول–مقصد، قرارداد واقعی، QC/صادرات |
| F — مالی و اجرای میدانی | [۰۳](03-financial-assumptions-and-gaps.md)، [۳۷](37-economic-flow-and-report-boundaries.md)، [۳۸–۴۱](38-partner-engagement-lifecycle.md) | ارقام فرضی در برابر اسناد واقعی؛ شریک و تحویل |
| G — حکمرانی و تغییر | [۴۲](42-business-governance-and-authority-map.md)، [۴۳](43-business-policy-and-change-versioning.md)، [۴۴](44-cross-engine-dependency-and-responsibility-matrix.md) | مرجع انسانی، نسخه/اثر و انتقال نابجای تصمیم |
| H — ثبت نتیجه آتی | [۲۰ — Business Gates](20-business-baseline-and-technical-admission-gates.md)، [۲۳](23-business-decision-evidence-review.md)، [۲۸](28-structural-coverage-and-deferred-final-review.md) | نتیجه واقعی برای هر **Scope و موتور مستقل**، نه تصویب یکجا |

**این جدول فقط ترتیب پیشنهادیِ مطالعه در آینده است**؛ به معنی درخواست اجرای همین حالای چک نهایی نیست.

### ضمیمه مطالعه راهبردیِ افزوده در v0.16

برای بخش فرصت بازار، ریسک و موضع رقابتی، [زمینه محیطی/ریسک منبع](49-strategic-environment-and-risk-structure.md) و [پنج نیرو/ذی‌نفعان/جایگاه‌یابی](50-competition-stakeholder-and-positioning-structure.md) را به بررسی آینده اضافه کنید. این دو سند **اثبات بازار یا تصحیح ادعاهای قدیمی نیستند**؛ تنها جایگاه آنها را در ساختار و شواهد مورد نیازشان مشخص می‌کنند. چک نهایی همچنان آغاز نشده است.

## ۲. تعریف ساختاری «چه چیزی آماده مطالعه است؟»

| بعد | آنچه در پیش‌نویس تهیه شده است | آنچه برای پایان Business لازم خواهد بود |
| --- | --- | --- |
| ارزش/مخاطب | دو موتور و گروه‌های مشتری/شریک | شواهد نیاز مشتری و دامنه قابل تصویب |
| جریان/فرآیند | مسیرها، نقاط تماس، دست به دست شدن اطلاعات و استثناها | نتیجه معتبر، مسئول و شرایط/سناریوهای پذیرش |
| داده/AI | واژگان داده، حق اشتراکِ مطرح‌شده، جایگاه پیشنهاد و متخصص | حقوق داده، محدودیت AI و شواهد ارزیابی |
| مسئولیت تجاری | خانواده قرارداد، تحویل، QC و وصول جدا | قرارداد/مرجع واقعی و اثر قانونی/مالی |
| مالی/اقتصادی | پرسش درآمد، هزینه، وجه و گزارش | مدل مستقل مبتنی بر مدارک؛ حل FIN-001..007 |
| حاکمیت/گیت | دفتر تصمیم، تغییر نسخه و گیت مستقل دو موتور | اختیارات انسانی و تصویب محدوده هر موتور |
| UI/Technical | تنها نیازهای کاربر و مرزهای کیفی | **پس از تصویب Business** مطالعه فناوری/معماری/ADR |

## ۳. قفل‌های تصمیم تا زمان دستور مشخص کارفرما

- **«ساختار آماده مطالعه» ≠ «تمام ساختار به‌صورت نهایی صحیح و کامل است».**
- در این فاز **نیاز به انتخاب MVP/اولویت واقعی، منطقه/مقصد، قراردادها، بانک، نرخ، مدل AI، فناوری، صاحب اختیار/امضاکننده یا ثبت شرکت مطرح نمی‌شود**. این‌ها در جای درست خود **OPEN** می‌مانند و مانع تبدیل ساختار به عملکرد واقعی خواهند بود.
- ساختار شامل تنها **دو موتور تجاری** است؛ توانمندسازهای محتوا/AI/داده/گزارش/پشتیبانی در نقش موتور سوم یا منبع مجوز خودکار قرار نمی‌گیرند.
- PR #6 تنها نمونه FastAPI اکتشافی در **HOLD** است؛ موفقیت CI آن پشته را مصوب نمی‌کند.
- تصمیم واقعی درباره پذیرش Business برای Domestic و Export باید با **دو پرونده گیت جدا و شواهد** انجام شود؛ تأیید یک موتور گیت دیگری را نمی‌گذراند.

## ۴. چیزی که بسته حاضر انجام نداده است

**انجام نشده:** ممیزی سطر به سطر ۳۷ صفحه سند مبنا، مصاحبه با ذی‌نفعان، ارزیابی بازار/قانون/کیفیت واقعی، اعتبارسنجی مدل مالی، شناسایی همکار واقعی، طراحی UX قابل آزمون، معماری فنی یا مدل داده/API، آزمون عملیاتی، تأیید Business Gate، پذیرش Code Review/Stage/QA/Production.

**انجام شده:** یک مرجع یکپارچه و دفتر اقلام شناخته‌شده‌ی باز در سطح ساختار پیش‌نویس؛ همراه با برنامه مطالعه بعدی بدون ادعای اتمام/تأیید.

## ۵. وضعیت نگهداری و پرونده‌های باز

| موضوع | وضعیت |
| --- | --- |
| [Business PR #1](https://github.com/mahdimarzooghi4-debug/Ronas/pull/1) | DRAFT / OPEN / UNMERGED |
| [Domestic Issue #2](https://github.com/mahdimarzooghi4-debug/Ronas/issues/2) | BUSINESS GATE OPEN |
| [Export Issue #3](https://github.com/mahdimarzooghi4-debug/Ronas/issues/3) | BUSINESS GATE OPEN |
| [Finance Issue #4](https://github.com/mahdimarzooghi4-debug/Ronas/issues/4) | FIN-001..007 OPEN |
| [Exploratory Code PR #6](https://github.com/mahdimarzooghi4-debug/Ronas/pull/6) | HOLD, not approved architecture |
| Integrated Final Review | DEFERRED by RON-DEC-008 |

**Next structural mode:** only if further uncovered *structural* dimensions emerge, supplement those with source/role links; otherwise wait for explicit authorization to run the integrated review. Creating more documents just for document count is not itself progress.
