# Ronas Technical Discovery — Charter و مرز گیت‌ها | DRAFT

**Status:** NONBINDING TECHNICAL STRUCTURE STUDY / NO ADMISSION / NO IMPLEMENTATION.

## ۱. حقیقت موجود از Business

| مبنای قابل استناد | آیا مصوب است؟ | پیامد محدود برای مطالعه فنی |
| --- | --- | --- |
| دو موتور Domestic و Export با قراردادها و Business Gate مستقل (RON-DEC-001) | APPROVED | گزینه‌های دامنه‌ای باید اختلاط تعهد/داده/وجوه را بررسی کنند؛ **توپولوژی استقرار هنوز معلوم نیست** |
| رویکرد Export چندمدلی با قرارداد **مستقل برای هر رابطه** (RON-DEC-003) | APPROVED DIRECTION ONLY | مطالعه امکان نمایش ارتباط بین تعهدها؛ **نوع قرارداد، درصد و مالکیت کالا فنی مصوب نیست** |
| Business → Technical → Backlog → Sprint → Code → ... (RON-DEC-007) | APPROVED PROCESS | هیچ جهش به انتخاب Stack/Contract/کد بدون قبولی گیت‌ها |
| ساختار پیش از چک نهایی (RON-DEC-008) | APPROVED SEQUENCING | [چک اولیه منبع و ساختار](../business/51-integrated-business-review-findings.md) اکنون ثبت شده ولی **Business Gates هنوز OPEN هستند** |
| ۱۹ جریان D-01..10 و E-01..09 و هفت گروه LX | STRUCTURAL DRAFT | فقط نگاشت موضوع/مسئولیت برای مطالعه؛ **User Story یا endpoint مصوب نیست** |
| دامنه اجرا، بانک، QC، داده/AI، مدل مالی/تعهد | OPEN | هیچ راهکار اجرایی/Provider/ورود Production پیشنهادِ لازم‌الاجرا نمی‌شود |

## ۲. هدف خروجی Technical Discovery (نه تصویب)

- ارائه **تقسیم‌بندی منطقی نامزد** بر اساس مالکیت مفهومی اطلاعات و رویدادهای کسب‌وکار، مستقل از تعداد مخزن، دیتابیس، تیم یا Runtime.
- طرح **سؤال‌های معماری** درباره مرز امنیت، کیفیت شواهد، محرمانگی، خطا، دسترسی، هویت، AI و وابستگی بیرونی.
- فهرست **گزینه‌های جایگزین** و روش مقایسه برای ADR آینده بدون نتیجه‌سازی و تعصب نسبت به فناوری قبلی.
- نگاشت **شرایط ورود واقعی** از Business Contract مصوب یک موتور/Scope به طراحی Technical همان محدوده.

## ۳. چیزهایی که هنوز حق قفل‌کردنشان را نداریم

| موضوع | وضعیت Discovery | چرا تعیین نمی‌شود؟ |
| --- | --- | --- |
| نام و تعداد اپلیکیشن‌ها/پنل‌ها | OPEN | مخاطب، کانال، سفر و مجوز واقعی تصویب نشده |
| مرزبندی Codebase/Service/Database | OPTIONS ONLY | استقلال Business لزوماً به تفکیک فیزیکی منجر نمی‌شود |
| زبان و Framework | UNSELECTED | نیازهای قابل اندازه‌گیری و معیار هزینه/نگهداری آماده نیست |
| مدل داده و State Machine | UNAPPROVED | قرارداد حقوقی/کیفی/مالی و حالات خطا باز است |
| هوش مصنوعی و Multi-agent | UNSELECTED | حق داده، کارکرد و روش ارزیابی/مرجع انسانی تصویب نشده |
| پرداخت، بانک، صادرات، QC | NO LIVE PARTNER | منبع رسمی/قرارداد/قواعد امنیت و انطباق وجود ندارد |
| غیرعملکردی‌ها/NFR | NEED BUSINESS EVIDENCE | ظرفیت، SLO، RPO/RTO، latency، residency و acceptance numeric نداریم |

## ۴. جریان حاکمیت Technical واقعی پس از Business

```text
Approved Business Scope for engine D or E + owner + evidence
    -> Technical Requirements and NFR acceptance per scope
    -> candidate architecture alternatives and tradeoff record
    -> explicit approved ADRs and Technical Contract
    -> independently admitted Product Backlog
    -> Sprint Authorization -> Code -> Code Review -> Stage -> QA -> Release -> Production ...
```

در شرایط کنونی فقط قسمت **candidate architecture alternatives and questions** انجام می‌شود و هر خروجی برای پذیرش دوباره نیازمند تطبیق Scope مصوب است.

## ۵. خروجی و معیار صحت این Draft

- [x] تنها موضوعاتِ از قبل شناسایی‌شده در Business را به پرسش/گزینه معماری ترجمه کند.
- [x] هیچ نرخ، Threshold، نقش مجاز، State Machine، Provider، مدل AI، endpoint، db/schema یا latency تصنعی وارد نشود.
- [x] PR اکتشافی با شاخه جدا و حالت Draft/Open، بدون Code/CI جعلی نگهداری شود.
- [ ] تصویب Business Scope/Domestic Gate #2 و Export Gate #3 به‌صورت جدا انجام شود.
- [ ] پس از تصویب دامنه، ADRهای واقعی با شواهد انتخاب و امضا شوند.

**This charter is NOT Technical Approval.**
