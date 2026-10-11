# Ronas — Business-to-Technical Admission Matrix (No Gates Passed)

**Status:** PRE-ADMISSION CONTROL QUESTIONS / NOT TECHNICAL CONTRACT, RELEASE CHECKLIST OR CODE AUTHORIZATION.  
**Source:** [Business Review 51](../business/51-integrated-business-review-findings.md)، [Business Gate 20](../business/20-business-baseline-and-technical-admission-gates.md)، [Decisions](../business/04-decisions-and-open-questions.md)، [19 flows](../business/18-dual-engine-business-requirements.md).

## ۱. وضعیت شناسه‌ها و گیت‌های موجود

| دامنه | مبنای بررسی موجود | مانع اصلی | وضعیت ورود Technical |
| --- | --- | --- | --- |
| Domestic — Education/Cultivation | D-01/02/03/05/06, LD-01..06 | مخاطب و محصول/منطقه، حریم خصوصی، مرجع توصیه/کیفیت | **NOT ADMITTED**؛ فقط Context Question |
| Domestic — Equipment/Market | D-04/07 | فروشنده قانونی، انتشار/قیمت/ایمنی، قرارداد مالی | **NOT ADMITTED** |
| Domestic — Fulfilment/Finance | D-08/09/10 | هاب/رسید/خسارت، PSP/تسویه، مالیات، قرارداد | **NOT ADMITTED** |
| Export — Opportunity/Supply | E-01/02/03 | محصول–مقصد، طرف خارجی، معیار تأمین‌کننده و قانون | **NOT ADMITTED** |
| Export — Contracts/QC/Processing | E-04/05/06 | مالک کالا و شروط مستقل هر رابطه، QC/فرآوری/حمل | **NOT ADMITTED** |
| Export — Shipment/Financial | E-07/08/09 | صادرکننده قانونی، اسناد، وصول و صورت‌مالی قرارداد | **NOT ADMITTED** |
| Enabling — Identity/Data/AI | LX-IDENTITY/AI/KNOWLEDGE | سیاست داده، رضایت، ارزیابی علمی و اختیار انسان | **NOT ADMITTED** |
| Enabling — Review/Partner/Reporting | LX-EVIDENCE/PARTNERS/INSIGHTS/GOVERNANCE | شواهد واقعی، صلاحیت شریک، KPI/داده/اختیار | **NOT ADMITTED** |

## ۲. مدارک لازم برای پذیرش محدود و مستقل هر Scope

| مورد ورود به قرارداد Technical آینده | مثال نوع مدرک موردنیاز | وضعیت |
| --- | --- | --- |
| Scope و exclusions مصوب یک موتور | حوزه مخاطب/محصول/منطقه/مقصد؛ عملیات خارج از Scope | OPEN |
| مالک Business/اختیار واقعی | فرد/نهاد مجاز و دلیل اختیار قرارداد/کیفیت | OPEN |
| بازیگران، ورودی/خروجی، حالت نامعلوم و استثناها | مثال معتبر و موارد منفی/اختلاف | OPEN |
| رضایت، داده مجاز، حذف/نگهداری و اشتراک موتور | متن معتبر سیاست و آزمایش حقوق داده | OPEN |
| معیارهای اندازه‌پذیر کیفیت و عملکرد | سنجه قابل‌قبول و روش اندازه‌گیری | OPEN |
| تعامل واقعی شریک بیرونی | سند قرارداد، شواهد شناسایی و ریسک/مسئولیت | OPEN |
| ضوابط مالی/خوراکی/صادراتی در صورت Scope عملیاتی | صاحب قیمت، QC، مالک، وصول و تعهد | OPEN |
| تأیید رسمی Business Gate برای Scope دقیق | تصمیم/شواهد/تاریخ و استثناها در #2 یا #3 (و #4 برای مالی) | **NOT GRANTED** |

**مهم:** اگر در آینده Scope کوچک و غیرتجاری/فاقد PII با شواهد کافی تصویب شود، همان دامنه می‌تواند **گیت مستقل خودش** را طی کند؛ بازبودن بخش بازار/مالی دیگر **موجب تصویب خودکار نیست** و نباید هر بحث فنی را با موضوع مالی یکی کرد.

## ۳. خروجی‌هایی که در این فاز مجاز هستند

- نگاشت اصطلاحات Business به Contextهای **نامزد**.
- فهرست مخاطرات/نیاز داده و مرزهای حقوقی/امنیتی برای سؤال‌های ADR.
- مقایسه **گزینه‌های معماری** و ثبت عدم‌قطعیت، بدون Score ساختگی یا انتخاب Framework.
- عدم استفاده از داده یا سرویس واقعی/Secret/پروژه Production.

## ۴. خروجی‌هایی که در این فاز ممنوع‌اند

- تصویب خودکار و ثبت ADR با STATUS APPROVED؛ انتخاب Stack، Microservices، DB یا AI family.
- پیاده‌سازی دامنه، State Machine، مدل SQL، Endpoint، پرداخت و واردکردن داده واقعی.
- انتقال فایل خصوصی طرح‌نامه یا قرارداد محرمانه به Public GitHub.
- ادغام PR #6، شروع Sprint، CI پذیرش Stage/QA یا استقرار Production.

**Next gate:** تصمیم Business برای یک Scope مشخص و دارای شواهد، سپس Technical Contract و Technical Approval همان Scope؛ تا آن زمان **NONBINDING TECHNICAL DISCOVERY ONLY**.
