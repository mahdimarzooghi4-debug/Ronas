# Ronas — Candidate Context Responsibilities and Logical Interaction Map

**Status:** CANDIDATE BOUNDED-CONTEXT QUESTIONS / NOT DDD COMMITMENT, MICROSERVICE LIST, API, DATABASE OR EXECUTABLE EVENT SPEC.  
**Inputs:** [Business 19 flows](../business/18-dual-engine-business-requirements.md)، [LD/LE/LX responsibilities](../business/29-logical-product-responsibility-map.md)، [handoffs](../business/30-business-interaction-and-handoff-map.md)، [integrated atlas](../business/46-integrated-business-structure-atlas.md).  
**Rule:** «Context نامزد» محدوده واژگان و مسئولیت برای ارزیابی است؛ قطعه کد، تیم، کلاستر، دیتابیس یا Endpoint مجزا نیست.

## ۱. Domestic — مرزهای منطقی نامزد

| گروه Context نامزد | موضوعات Business | موضوع اصلیِ مالکیت مورد سؤال | مجوز/تعارضی که مانع قرارداد اجرایی می‌شود |
| --- | --- | --- | --- |
| D-A Membership / Learning | D-01 / D-03 | شرایط ارتباط اعضا و نسخه محتوای آموزشی | RON-OPEN-003/012/013، حقوق داده/محتوا |
| D-B Plot / Cultivation | D-02 / D-05 | وصف فضای کشت، مشاهده و منشأ داده | RON-OPEN-004/013، حق استفاده فضا/ایمنی |
| D-C Equipment Partner Discovery | D-04 | فروشنده تجهیزات، محصول و خدمات مرتبط | RON-OPEN-005، قرارداد فروش/گارانتی/کارمزد |
| D-D Harvest / Surplus | D-06 | اظهار برداشت و تمایلِ احتمالی عرضه | RON-OPEN-004/005، برداشت ≠ موجودی سالم قابل‌فروش |
| D-E Local Marketplace | D-07 | تعامل عرضه/تقاضا و توافق احتمالی | RON-OPEN-005/007، فروشنده، قیمت، رضایت |
| D-F Local Fulfilment / Casework | D-08 / D-09 | سند سپردن/تحویل و رسیدگی به اختلاف | RON-OPEN-006/015، ریسک و مرجع جبران |
| D-G Domestic Economic Records | D-10 | ادعای تعهد مالی، مدارک و گزارش هر رابطه داخلی | FIN-001..007، PSP و استاندارد مالی |

**نام‌های انگلیسی صرفاً برچسب‌های مقایسه‌اند؛ `D-A..G` قرارداد تایید‌شده‌ای برای تیم/سرویس/مدل داده نیست.**

## ۲. Export — مرزهای منطقی نامزد

| گروه Context نامزد | جریان | موضوع مالکیت و مسئولیت مورد بررسی | مانع قابل تبدیل به قرارداد |
| --- | --- | --- | --- |
| E-A Supplier / Capacity | E-01 | تأمین حرفه‌ای، ظرفیت اظهارشده و بررسی | RON-OPEN-008/015، قرارداد/مبنای ظرفیت |
| E-B Product–Destination / Market | E-02 / E-03 | نیازمندی مقصد، فرصت و اعتبار مشتری | RON-OPEN-008/010، قانون/استاندارد/خریدار |
| E-C Independent Commercial Relationships | E-04 | قراردادهای جداگانه/طرف‌ها و حق‌الزحمه | RON-OPEN-009/011، P/A/S/J فقط تحلیل |
| E-D Goods / QC / Processing | E-05 / E-06 | محموله/لات/آزمون و فرآوری/بچ | RON-OPEN-010، صاحب کالا و QC/استاندارد |
| E-E Export Trade & Logistics | E-07 / E-08 | اسناد فروش/صادرات/حمل/تحویل | RON-OPEN-008/010/011، صادرکننده مجاز |
| E-F Export Economic Records | E-09 | هر قرارداد مستقل، طلب/وصول/هزینه و وجه | FIN-001/004/006، عدم دوباره‌شماری |

**شریک فیزیکی مانند کارخانه/فورواردر با «Context» یکی نیست و یک Context به منزله امکان عقد قرارداد نیست.**

## ۳. نیازهای مشترک و پرسش درباره مالک داده

| Context یا قابلیت افقی نامزد | پشتیبانی موضوعی | مهم‌ترین سؤال Technical پس از Business |
| --- | --- | --- |
| Identity and Consent | LX-IDENTITY | آیا هویت مشترک با scope authorization مستقل و رضایت واقعی قابل بررسی است؟ |
| Content and Member Engagement | LX-KNOWLEDGE | حقوق نسخه محتوا/RXP/باشگاه چگونه جداگانه تعریف می‌شوند؟ |
| Evidence and Human Review | LX-EVIDENCE | شاهد چه کیفیت/منشأیی دارد و چه مرجعی واقعاً تصمیم می‌گیرد؟ |
| Partner Relationship Catalog | LX-PARTNERS | هر شریک با قرارداد/صلاحیت **موتور-مبنا** چگونه معرفی می‌شود؟ |
| AI Advisory / Evaluation Governance | LX-AI | داده مجاز، ارزیابی و Human Review چگونه در Business تعریف می‌شود؟ |
| Reporting / Governance | LX-INSIGHTS / LX-GOVERNANCE | aggregation scope، محرمانگی و عدم دوباره‌شماری چگونه کنترل می‌شوند؟ |

**نه «هویت واحد» به معنای اجازه مشترک است، نه «یک Context مالی» به معنای انتقال وجه.** ممکن است فناوری/زیرساخت مشترک بعداً اقتصادی باشد؛ بحث فقط پس از شواهد و امنیت.

## ۴. نقشه تعامل پیشنهادی — فقط سوال، نه Event/API

```text
Domestic:
Membership/learning (?) ⇄ Cultivation/observations (?)
  ⇢ Harvest statement (?) ⇢ Proposed offer (?)
  ⇢ Contractual sale (?) ⇢ Local delivery/evidence (?)
  ⇢ Dispute handling (?) / Separate economic evidence (?)

Export:
Professional supplier (?) + Market lead (?) + Product–destination (?)
  ⇢ Independent contract review (?) ⇢ Goods/QC/processing (?)
  ⇢ Authorized trade and transport (?) ⇢ Verified receivable/collection (?)

Enabling (if independently authorized):
Identity/consent + Content + Evidence/human review + Partner relation
+ AI advisory (not decisions) + Reporting/governance
```

علامت‌ها نشان‌دهنده **پرسش درباره اطلاعات قابل انتقال** هستند. هیچ ترتیب State Machine، موضوع Outbox، پیام یا Transaction مشخص تصویب نشده است.

## ۵. نقاط تحقیق مهم در Technical واقعی

1. آیا داده‌های مرتبط با خانوار و قراردادهای صادراتی به domain ownership جدا نیاز دارند و چه نوع isolation برای امنیت/هزینه متناسب است؟
2. چگونه منشأ مشاهده، سند، بررسی تخصصی، تصمیمِ صاحب اختیار و اثر تجاری *در صورت تصویب Business* تفکیک خواهند شد؟
3. چه رابطه‌ای میان معامله داخلی و شرکت/شریک واقعی وجود دارد، بدون فرض مالی یا هویت مشترک؟
4. آیا تعاملات میدانی (هاب، آزمایشگاه، کارخانه، گمرک) مبتنی بر ثبت نتیجه انسانی خواهند بود یا یکپارچه‌سازی واقعی؟ این مسئله Business و Provider evidence می‌خواهد.
5. معیار آزمون تغییر قرارداد/استاندارد/رضایت روی سوابق چیست؟ تا قرارداد تصویب نشده، Version semantics تعریف نمی‌شود.

**Cross-engine ownership: distinct Business obligations are APPROVED; physical separation remains an ADR question.**
