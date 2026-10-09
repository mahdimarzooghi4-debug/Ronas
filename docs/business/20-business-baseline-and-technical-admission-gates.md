# روناس — پرونده خط مبنای Business و گیت ورود به Technical | v0.10

**Status:** DRAFT / REVIEW PACKAGE — **NO ENGINE HAS PASSED ITS BUSINESS GATE**  
**Purpose:** اجرای واقعی تصمیم فرآیندی [RON-DEC-007](04-decisions-and-open-questions.md) بدون پرداختن به جزئیات سهام و ثبت شرکت؛ تعهدات واقعی حقوقی/مالی تجارت و سلامت همچنان در زمان ورود به عملیات باید اثبات شوند.  
**Trace:** [نیازمندی‌های ۱۹ جریان](18-dual-engine-business-requirements.md)، [کیفیت/مرزها](19-business-quality-attributes-and-invariants.md)، [گیت‌های مستقل](09-parallel-validation-and-business-gates.md)، [ممیزی مالی](03-financial-assumptions-and-gaps.md).

## ۱. تفکیک چهار نوع گزاره

| سطح | معنی | نمونه از روناس | آیا اجازه Code عملیاتی می‌دهد؟ |
| --- | --- | --- | --- |
| **SOURCE** | گزاره طرح‌نامه، لزوماً معتبر/مصوب نیست | «مازاد خودکار وارد بازار شود» و «پلتفرم مستقیم بخرد» | خیر |
| **APPROVED DIRECTION** | تصمیم کلی کارفرما با دامنه روشن | دو موتور مستقل؛ مدل ترکیبی Export؛ فرآیند توسعه | به‌تنهایی خیر |
| **PROPOSED / OPEN** | گزینه یا نیازمند تصمیم/شواهد | مسئول QC، قیمت، ورود عضو، داده، پرداخت، قرارداد مشخص | خیر |
| **APPROVED CONTRACT + GATE** | تصمیم دقیق، صاحب اختیار، شواهد، دامنه و معیار پذیرش ثبت و تأیید شده | **هنوز برای هیچ موتور ثبت نشده** | تنها در دامنه همان گیت، سپس Technical/Backlog/Sprint لازم است |

## ۲. تعارض‌های قابل اثبات منبع و پرسش تصمیم

| کد | گزاره‌ها و منشأ | ریسک تبدیل مستقیم به محصول | تصمیم لازم / وضعیت |
| --- | --- | --- | --- |
| BC-01 Domestic Auto Surplus | طرح‌نامه، صفحه فایل ۵: مازاد برداشت «به‌صورت خودکار» وارد بازار می‌شود؛ فایل‌های Domestic 01 و 06 | انتشار خوراکی بدون سند ایمنی، حق فروشنده/قیمت | DOM-DEC-03/06/07 و RON-OPEN-004/005؛ **OPEN** |
| BC-02 Pricing | طرح‌نامه صفحات فایل ۹–۱۰: هم کشف قیمت عرضه/تقاضا و هم مبنای هزینه+سود مطرح است | الگوریتم/سود تحمیلی بدون اختیار | **RON-DEC-009 نقش بازارگاه واسطه‌ای و RON-DEC-010 اختیار قیمت نهایی تولیدکننده برای محصول خانگی را تصویب کرده‌اند**؛ اختلاف روایت‌های SOURCE به تصمیم «قیمت با تولیدکننده؛ پیشنهاد اختیاری روناس» محدود شده، اما الگوریتم پیشنهاد، مذاکره/تخفیف، کارمزد و شرایط قرارداد **OPEN** هستند |
| BC-03 Direct Export Buy | طرح‌نامه صفحه فایل ۵: خرید مستقیم و فرآوری؛ فایل Export 02 | تعهد قطعی خرید، مالکیت و موجودی بدون قرارداد | RON-DEC-003 فقط مسیر چندقراردادی را مصوب کرده؛ معامله P جدا **OPEN** |
| BC-04 Export Profit Share | طرح‌نامه صفحات فایل ۲۷/۳۵: مثال سهم سود صادرات/عضویت؛ فایل ممیزی مالی 03 | نرخ و درآمد/سود ساختگی؛ دوباره‌شماری | هر توافق P/A/S/J و FIN-004 جدا **OPEN**؛ مثال ۳۰٪ تصمیم نیست |
| BC-05 Finance Scope | فصل مالی، صفحه فایل ۲۴ «فقط داخلی» اما جداول صفحات ۳۵–۳۶ صادرات را نیز وارد کرده‌اند | بودجه و جریان نقدی تلفیقی نامعتبر | FIN-001..007، Issue #4؛ **OPEN** |
| BC-06 AI and Food/Trade | طرح‌نامه، مقدمه و صفحات ۵/۱۹–۲۰: پیشنهاد AI برای کشت/بازار | تشخیص، QC، صلاحیت، قیمت یا خرید بدون ارزیابی/مسئولیت | RON-OPEN-012/013/004/010؛ **OPEN** |

**روش کار:** این جدول تنها **تعارض/فاصله ادعای منبع تا تصمیم محصول** را گزارش می‌کند. جهت تأیید هر تعبیر، متن اصل سند/شواهد و نظر صاحب اختیار باید بررسی شود؛ نه اینکه تعارض با حدس حل یا حذف شود.

## ۳. پرونده Business Gate — Domestic (OPEN)

| بلوک پیش‌نیاز | خروجی لازم برای گیت | وضعیت فعلی |
| --- | --- | --- |
| ارزش و قلمرو | گروه کاربران، منطقه/محصول/دامنه پایلوت، موارد صریحاً خارج از دامنه | OPEN — DOM-DEC-01/02 |
| ثبت/آموزش/ایمنی | تفاوت آموزش و عرضه خوراکی، مرجع QC و اختیار فردی | OPEN — DOM-DEC-03/04/07 |
| بازار و تجهیزات | فروشنده قانونی، حق قیمت‌گذاری، مدل عرضه/تجهیز، سیاست عودت | **PARTIAL — نقش واسطه‌ای در RON-DEC-009 و اختیار قیمت نهایی تولیدکننده در RON-DEC-010 APPROVED**؛ روش پیشنهاد قیمت، قرارداد/کمیسیون/ایمنی/تجهیزات و ورود مازاد (DOM-DEC-05/07) همچنان OPEN |
| تحویل و اختلاف | طرف هاب/حمل، شواهد تحویل، کیفیت، خسارت و رسیدگی | OPEN — DOM-DEC-08/10 |
| داده و درآمد | رضایت و دسترسی، مسیر PSP/تسویه و مدل مالی مستقل | OPEN — RON-OPEN-007/013/014 |
| Business Acceptance | متن تصمیم، مدارک، نقش پاسخگو، دامنه و امضای مجاز | NOT RECORDED — #2 |

**شرط مهم:** می‌توان برای قابلیت‌های محدودترِ غیرتجاری **بسته Business مستقل** تعریف کرد، اما فقط با تعیین صریح کاربران/داده/رضایت/حذف و معیار پذیرش همان دامنه و تأیید گیت آن؛ نباید فقدان قرارداد فروش و PSP را بی‌صدا مجوز فعالیت تجارت دانست.

## ۴. پرونده Business Gate — Export (OPEN)

| بلوک پیش‌نیاز | خروجی لازم برای گیت | وضعیت فعلی |
| --- | --- | --- |
| ارزش/مقصد | محصول واقعی، مقصد، خریدار/بازار هدف و مدارک قابل اتکا | OPEN — EXP-DEC-02/03/07 |
| مدل قراردادی | پرونده و نقش تجاری مستقل برای هر توافق، مالکیت و مسئول | جهت‌گیری چندمدلی APPROVED؛ قراردادهای خاص OPEN |
| شواهد تأمین و QC | مدارک ظرفیت، استاندارد مقصد، فرآوری، لات/بچ، رد/فراخوان | OPEN — EXP-DEC-03/05/06 |
| عملیات صادرات | صادرکننده واقعی، اسناد گمرکی، حمل، بیمه و مسئول خسارت | OPEN — EXP-DEC-07/08 |
| ارز و مالی | وجه/مالیات، هزینه، کارمزد/سود هر قرارداد، مدل مستقل Export | OPEN — EXP-DEC-09/10, FIN-004 |
| Business Acceptance | متن تصمیم، مدارک، نقش پاسخگو، دامنه و امضای مجاز | NOT RECORDED — #3 |

**استقلال گیت:** گذر Domestic، وضعیت Export را تغییر نمی‌دهد و بالعکس. مدل چندقراردادیِ مصوب فقط جهت‌گیری طراحی است، نه تأیید هیچ معامله یا نوع درآمد.

## ۵. قالب رسمی گزارش پذیرش Business (برای هر موتور و محدوده جدا)

```text
Business Gate Record ID:
Engine: DOMESTIC | EXPORT
Scope of this approval and excluded capabilities:
Business objective and audience:
Cited source/document versions and conflict IDs:
Approved decisions and named accountable approver:
Actor/owner and permission boundaries:
Data input/provenance, consent and sensitive fields:
Financial/quality/legal dependencies as applicable:
User journeys, adverse scenarios and exception handling:
Acceptance evidence and observable exit tests:
Risks, unresolved questions and explicit exclusions:
Disposition: APPROVED | REJECTED | DEFERRED | OPEN
Approval date/effective version and audit evidence:
Authority to enter Technical for this specific scope: YES/NO
```

**قواعد گیت:** نتیجه `APPROVED` فقط با تصمیم واقعی و شواهد به دست می‌آید، نه با تکمیل خودکار فرم. `Authority to enter Technical` باید **متناسب با همان Scope** باشد؛ هیچ تأیید پیش‌فرض، آستانه ساختگی یا تغییر ضمنی به `YES` وجود ندارد.

## ۶. مسیر گیت‌های بعدی و وضعیت فعلی

1. **Business Foundation/Review:** پرونده‌های D-01..D-10 و E-01..E-09 و تعارض BC-01..06 را با صاحب تصمیم و شواهد مرور و نیازمندی‌های واقعی را برای دامنه مشخص تصویب کنید.
2. **Business Gate محدود/مستقل:** برای هر موتور نتیجه و محدوده ورود را جداگانه و صریح ثبت کنید؛ موارد OPEN را مستثنا کنید، نه آنکه مقدار پیش‌فرض بگذارید.
3. **Technical:** تنها برای دامنه پذیرفته‌شده، قیود و ویژگی‌های کیفی را به معیار قابل آزمون تبدیل، گزینه‌های پشته/معماری را با ADR مقایسه و تصمیم مصوب بگیرید. **Python/FastAPI تنها گزینه اکتشافی قبلی است**.
4. **Product Backlog → Sprint Authorization:** Story و معیار پذیرش و وابستگی را از قرارداد مصوب استخراج و اسپرینت را *پیش از* کدنویسی تأیید کنید.
5. **Code → Code Review → Stage → QA/Testing → Release Approval → Production → Monitoring → Improvement:** هر گیت به‌صورت مستقل بررسی شود؛ CI سبز به‌معنای مجوز استقرار نیست.

### وضعیت PRها

- [PR #1 — Business](https://github.com/mahdimarzooghi4-debug/Ronas/pull/1): Draft/Open؛ این بسته تنها مواد بررسی را کامل‌تر می‌کند، **نه** اینکه Business Gate پاس شده باشد.
- [PR #6 — exploratory code on HOLD](https://github.com/mahdimarzooghi4-debug/Ronas/pull/6): Draft/Open، کد قبل از تصویب Technical نوشته شده؛ **نه ادغام، نه توسعه فیچر، نه Stage/Production**.
- [Issue #2 Domestic](https://github.com/mahdimarzooghi4-debug/Ronas/issues/2)، [Issue #3 Export](https://github.com/mahdimarzooghi4-debug/Ronas/issues/3)، [Issue #4 Finance](https://github.com/mahdimarzooghi4-debug/Ronas/issues/4): همه OPEN و نیازمند تصمیم/شواهد واقعی.

**Business Service Blueprint v0.9:** [Domestic journeys](21-domestic-service-blueprints.md) و [Export journeys](22-export-service-blueprints.md) و [Decision/Evidence Review](23-business-decision-evidence-review.md) نقشه‌های پیشنهادی و سؤالات پذیرش‌اند؛ **Business Gate هیچ موتوری را PASS نمی‌کنند**. مرز نقش، رویداد، مدرک، مانع و تصمیم‌گیر باید برای هر Scope جداگانه تصویب شود.

**v0.10 Structural-first sequencing:** [نقشه جامع قابلیت‌ها](24-complete-business-structure-map.md)، [نقش‌ها و تجربه](25-actors-channels-and-workspaces.md)، [اطلاعات مفهومی](26-conceptual-information-structure.md)، [خدمات و مرزها](27-shared-services-and-external-boundaries.md) و [دفتر پوشش](28-structural-coverage-and-deferred-final-review.md) برای **تکمیل ساختار پیش از بازبینی نهایی** ایجاد شده‌اند. این‌ها Approved Business Contract یا Technical Architecture نیستند؛ گیت‌ها OPEN می‌مانند و PR #6 در HOLD است.

**Legal focus boundary:** ثبت شرکت، سهم‌الشرکه و ترکیب شرکا در این مسیر محصول پیگیری نمی‌شوند؛ این موکول‌کردن به معنی مجازبودن پرداخت/صادرات/عرضه خوراکی بدون رعایت قانون نیست.
