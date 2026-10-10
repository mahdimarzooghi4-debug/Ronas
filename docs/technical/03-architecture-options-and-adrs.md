# Ronas — Architecture Alternatives and ADR Preparation (No Selection)

**Status: OPTIONS FOR DISCOVERY / NO RECOMMENDED OR APPROVED STACK, TOPOLOGY, DB, FRONTEND, AI MODEL OR CLOUD.**  
**Basis:** [Review 51](../business/51-integrated-business-review-findings.md)، [candidate contexts](01-candidate-contexts-and-interactions.md)، [quality/data questions](02-data-trust-and-integration-questions.md)، RON-DEC-007.

## ۱. گزینه‌های قابل مقایسه (NOT DECIDED)

| محور تصمیم | گزینه‌های مطالعه، نه رأی نهایی | شواهد/معیارهایی که فعلاً در اختیار نداریم |
| --- | --- | --- |
| سبک سازماندهی منطق | **Modular Monolith**؛ **Context-specific independent services**؛ **Hybrid** | مرز داده واقعی، پیچیدگی قراردادها، مهارت نگهداری، حجم تغییر و نیاز استقلال استقرار |
| ذخیره‌سازی و مرزبندی داده | یک بستر با جداسازی منطقی/مالکیت؛ مخازن فیزیکی مستقل؛ ترکیبی | حق داده، انطباق، محرمانگی، transaction boundaries، هزینه و RPO |
| ارتباط اجزا | فراخوانی درون‌فرایندی؛ تعامل request/response؛ تبادل پیام/رویداد؛ ترکیبی | انطباق نیاز Sync/Async، ثبت مدرک، ترتیب، تحمل تکرار، خطای شریک |
| رابط کاربر | وب پاسخگو؛ اپ موبایل؛ رابط‌های نقش‌محور/ترکیبی | نیاز واقعی کانال/آفلاین/زبان/دسترس‌پذیری و بودجه |
| استقرار/اپراتوری | مدیریت‌شده، اختصاصی یا ترکیبی | اقامت داده، امنیت و هزینه، امکانات نیرو و قرارداد عملیات |
| هویت/مجوز | راهکار متمرکز با حدود موتور؛ راهکارهای تفکیک‌شده؛ مدل ترکیبی | سیاست نقش/رضایت مصوب و داده کاربران |
| Integration | کار انسانی و سند بررسی‌شده؛ اتصال مستقیم شریک؛ روش ترکیبی | قرارداد Provider، فرمت/کیفیت داده و قانون |
| AI / تحلیل | **عدم اجرای AI تا زمان قرارداد**؛ محتوای تخصصی/پیشنهاد انسانی؛ گزینه‌های مدل پس از ارزیابی | مسئله AI مصوب، داده مجاز، معیار خطا، قابلیت بازبینی، محدودیت زیرساخت |
| زبان/Framework/DB/Product | **UNSELECTED**؛ انتخاب نام/نسخه فقط پس از سنجه و ADR | برنامه تیم/هزینه/قابلیت نگهداری/الزام‌های دامنه |

**نکته:** این جدول درباره *trade-offs ممکن* است و حتی Modular Monolith را «انتخاب پیش‌فرض» اعلام نمی‌کند. PR #6 با FastAPI هیچ امتیاز یا مجوز پیشینی در این مقایسه ندارد.

## ۲. ADRهای پیشنهادی به عنوان پرونده سؤال (NOT DECISIONS)

| ADR candidate | مسئله قابل طرح | شرط تصمیم‌گیری |
| --- | --- | --- |
| TECH-ADR-DRAFT-01 | مرزهای Domain و مالکیت اطلاعات دو موتور | Business contract, isolation policy, data flow evidence |
| TECH-ADR-DRAFT-02 | Physical deployment/topology و مرز تیم/سرویس | بار، SLO و توان نگهداری واقعی |
| TECH-ADR-DRAFT-03 | Data store/consistency/audit/retention | حق داده، سابقه مالی/کیفیت و سیاست تصحیح |
| TECH-ADR-DRAFT-04 | IAM/Consent/Privacy | بازیگر مجاز، تغییر نقش و قانون نگهداری |
| TECH-ADR-DRAFT-05 | Offline/field-to-digital integration | سفر نقش‌ها، اصالت شواهد و شریک واقعی |
| TECH-ADR-DRAFT-06 | Evidence/QC/contract review boundaries | معیار علمی/حقوقی/مالی و مرجع انسانی |
| TECH-ADR-DRAFT-07 | AI architecture and governance | task/dataset/model benchmark and permissions |
| TECH-ADR-DRAFT-08 | Framework/database/mobile/hosting choices | سنجه‌های performance, maintainability, cost, security |
| TECH-ADR-DRAFT-09 | Monitoring, backup/recovery, resilience | SLO/RTO/RPO, operations capability |

**هیچ `TECH-ADR-DRAFT-xx` یک ADR تصویب‌شده، Issue مستلزم حل فوری یا انتخاب فناوری نیست.**

## ۳. قالب تصمیم Technical برای استفاده در زمان مجاز

```text
Decision ID and version:
Approved Business Engine/Scope and Gate Evidence:
Problem and constraints from real users/contracts/NFR:
Candidate alternatives and cost/security/operability trade-offs:
Evidence from benchmark, testing or documented assumptions:
Data/privacy/financial/QA/AI risk boundaries:
Decision and responsible Technical approver:
Rejected alternatives, reasons and open questions:
Migration/rollback/review and validity period:
Status: DISCOVERY -> PROPOSED -> APPROVED only by explicit authority
```

این قالب **State Machine اجرایی نیست**. گذار به APPROVED تنها طبق RON-DEC-007 و تأیید مشخص ممکن است.

## ۴. تمایز معماری و کدنویسی اکتشافی

- **کد موجود PR #6:** معادل تائید FastAPI یا نیاز Backlog نیست. این PR Draft/Open/HOLD باقی می‌ماند.
- **Draft Technical branch:** محتوا صرفاً Markdown و فاقد کد عملیاتی است؛ نه CI موفقِ جدید ادعا می‌شود نه Stage/Production.
- **اولین ADR واقعی:** فقط بعد از قرارداد Business قابل پذیرش و معیار ارزیابی/منبع معتبر؛ ترجیح فناورانه از روی عادت اتخاذ نشود.

**Outcome: architecture option-space documented, no decision.**
