# روناس — نقشه مرجع یکپارچه ساختار کسب‌وکار | Structural Draft v0.16

**Status:** INTEGRATED VIEW OF EXISTING BUSINESS DRAFTS / NOT A FINAL SOURCE AUDIT, APPROVED CONTRACT OR TECHNICAL ARCHITECTURE.  
**Goal:** خواندن تمام نمای محصول از **یک نقشه مرجع** با حفظ جزییات در اسناد تخصصی، بدون ایجاد موتور تجاری سوم و بدون اعلام تکمیل نهایی.  
**Inputs:** [Business Foundation](00-business-foundation.md)، [Domestic](01-domestic-engine.md)، [Export](02-export-engine.md)، [۱۹ جریان](18-dual-engine-business-requirements.md)، [ساختار قابلیت‌ها](24-complete-business-structure-map.md)، [نقش و داده](25-actors-channels-and-workspaces.md)، [مفاهیم داده](26-conceptual-information-structure.md)، [تعاملات](30-business-interaction-and-handoff-map.md)، [مرز مسئولیت](44-cross-engine-dependency-and-responsibility-matrix.md).  
**Evidence discipline:** `SOURCE` طرح‌نامه ≠ `APPROVED` تصمیم کارفرما؛ `PROPOSED` طرح تحلیلی ≠ قابلیت عملیاتی. این سند **خلاصه ساختار اسناد فعلی** است، نه اثبات صحت آنها.

## ۱. یک نمای کلان، با سه لایه متفاوت

```text
RONAS (product/business concept)
│
├── موتور Domestic — قراردادها، بازار، ریسک و Business Gate مستقل [RON-DEC-001]
│   ├── شناخت عضو و امکان کشت              D-01 / D-02
│   ├── آموزش، برنامه و مشاهده             D-03 / D-05
│   ├── تأمین تجهیزات                    D-04
│   ├── برداشت و اظهار مازاد               D-06
│   ├── بازار، تحویل، اختلاف               D-07 / D-08 / D-09
│   └── اقتصاد و شواهد مالی داخلی          D-10
│
├── موتور Export — قراردادها، تجارت، ریسک و Business Gate مستقل [RON-DEC-001]
│   ├── تأمین‌کننده، محصول–مقصد، فرصت     E-01 / E-02 / E-03
│   ├── روابط تجاری با قرارداد مستقل       E-04 [RON-DEC-003 DIRECTION]
│   ├── QC و فرآوری                      E-05 / E-06
│   ├── فروش، صادرات و تحویل              E-07 / E-08
│   └── اقتصاد، هزینه و وصول هر قرارداد   E-09
│
└── لایه توانمندساز (NOT a third commercial engine)
    ├── هویت، نقش، رضایت/حق داده           LX-IDENTITY
    ├── محتوای آموزشی، باشگاه و RXP         LX-KNOWLEDGE
    ├── تحلیل و پیشنهاد هوشمند             LX-AI
    ├── شواهد، ارزیابی تخصصی و ممیزی        LX-EVIDENCE
    ├── همکاری شرکا، ارتباطات و پشتیبانی    LX-PARTNERS
    ├── پرسش‌های گزارش و سنجش             LX-INSIGHTS
    └── تصمیم/گیت Business و تغییر          LX-GOVERNANCE
```

**درخت فوق نقشه کسب‌وکار است؛ نه نقشه ماژول، سرویس، API، سیستم مجوز یا قرارداد.** هم‌زمانی فعالیت دو موتور به معنای اشتراک وجوه، انبار، مجوز عرضه، کاربران یا اطلاعات حساس نیست.

## ۲. نمای یکپارچه جریان ارزش Domestic

| گروه/جریان | چرا مطرح است | مرجع تفصیلی ساختار | تفاوتی که نباید نادیده گرفته شود |
| --- | --- | --- | --- |
| D-01 عضویت و شناخت مخاطب | نقطه ارتباط خانوار | [۲۱](21-domestic-service-blueprints.md)، [۲۵](25-actors-channels-and-workspaces.md) | عضو بودن ≠ فروشنده مجاز |
| D-02 فضای کشت | تعریف زمینه تولید | [۲۱](21-domestic-service-blueprints.md)، [۲۶](26-conceptual-information-structure.md) | اظهار فضا ≠ ایمنی/حق استفاده تأییدشده |
| D-03 راهنمای کشت | آموزش/برنامه پیشنهادی | [۲۱](21-domestic-service-blueprints.md)، [۲۷](27-shared-services-and-external-boundaries.md) | پیشنهاد AI/کارشناس ≠ تأیید الزام‌آور |
| D-04 تجهیزات و فروشندگان | تأمین خدمت/کالا | [۳۴](34-partner-ecosystem-and-relationship-map.md)، [۳۵](35-business-commercial-responsibility-map.md) | فروشنده تجهیز ≠ مالک محصول خانگی |
| D-05 پایش | ثبت مشاهده/فعالیت | [۲۶](26-conceptual-information-structure.md)، [۳۹](39-physical-digital-operations-map.md) | تصویر/یادداشت ≠ سنجش معتبر |
| D-06 برداشت/مازاد | اظهار نتیجه کشت | [۲۱](21-domestic-service-blueprints.md)، [۳۰](30-business-interaction-and-handoff-map.md) | ثبت برداشت ≠ موجودی قابل عرضه |
| D-07 بازار محلی | مواجهه عرضه و تقاضا | [۳۵](35-business-commercial-responsibility-map.md)، [۴۱](41-operations-evidence-and-escalation-map.md) | عرضه ≠ قرارداد/پرداخت پذیرفته‌شده |
| D-08 تحویل | اتصال هاب/پیک و گیرنده | [۳۸](38-partner-engagement-lifecycle.md)، [۳۹](39-physical-digital-operations-map.md) | تصرف/حمل ≠ مالکیت یا وصول |
| D-09 اختلاف | اعتراض، خسارت و رسیدگی | [۳۲](32-exceptions-and-human-decision-points.md)، [۴۱](41-operations-evidence-and-escalation-map.md) | ادعا ≠ رأی قطعی/بازپرداخت |
| D-10 امور مالی | تفکیک ادعا، قرارداد و وجه | [۳۷](37-economic-flow-and-report-boundaries.md)، [۳۶](36-management-reporting-and-metric-candidates.md) | ثبت رقم ≠ وجه واقعی/سود |

**باز بودن گیت:** Scope داخلی، ایمنی خوراکی، فروشنده قانونی، قیمت، لجستیک، پرداخت، رضایت و اختیار انسانی هنوز در [Issue #2](https://github.com/mahdimarzooghi4-debug/Ronas/issues/2) OPEN هستند.

## ۳. نمای یکپارچه جریان ارزش Export

| جریان | وظیفه مفهومی | مرجع جزئیات | تفکیک مهم |
| --- | --- | --- | --- |
| E-01 تأمین‌کننده حرفه‌ای | ظرفیت/امکان همکاری | [۲۲](22-export-service-blueprints.md)، [۳۸](38-partner-engagement-lifecycle.md) | ظرفیت اظهارشده ≠ تعهد خرید |
| E-02 محصول–مقصد | مشخصات و استاندارد | [۲۲](22-export-service-blueprints.md)، [۳۹](39-physical-digital-operations-map.md) | استاندارد مقصد باید واقعی و مشخص شود |
| E-03 تقاضا/خریدار | شناسایی فرصت | [۲۲](22-export-service-blueprints.md)، [۳۶](36-management-reporting-and-metric-candidates.md) | Lead ≠ قرارداد فروش |
| E-04 قرارداد تأمین/رابطه تجاری | بررسی مدل چندقراردادی مستقل | [۱۱](11-export-multicontract-direction.md)، [۱۲](12-export-contract-review-dossier.md)، [۳۵](35-business-commercial-responsibility-map.md) | P/A/S/J دسته‌های پیشنهادی‌اند، نه قراردادهای فعال |
| E-05 تحویل و QC | شاهد آزمون/کیفیت کالا | [۲۶](26-conceptual-information-structure.md)، [۴۱](41-operations-evidence-and-escalation-map.md) | گزارش آزمون ≠ تأیید قطعی صادرات |
| E-06 فرآوری | تبدیل، بچ/لات، ضایعات | [۲۲](22-export-service-blueprints.md)، [۳۹](39-physical-digital-operations-map.md) | فرآوری ≠ انتقال مالکیت |
| E-07 فروش خارجی | طرف‌های معتبر و شروط تجارت | [۳۵](35-business-commercial-responsibility-map.md)، [۴۲](42-business-governance-and-authority-map.md) | فرصت ≠ تعهد الزام‌آور |
| E-08 صادرات/تحویل | مدارک حمل، ترخیص و مسئول ریسک | [۳۹](39-physical-digital-operations-map.md)، [۴۱](41-operations-evidence-and-escalation-map.md) | تحویل ≠ وصول |
| E-09 امور مالی و وصول | تفکیک اقتصاد **هر قرارداد** | [۳۷](37-economic-flow-and-report-boundaries.md)، [۴۳](43-business-policy-and-change-versioning.md) | سهم سود مثال طرح ≠ نرخ معتبر |

**باز بودن گیت:** محصول–مقصد، صادرکننده قانونی، قراردادی بودن مالکیت، QC، فرآوری، حمل و وجه هنوز در [Issue #3](https://github.com/mahdimarzooghi4-debug/Ronas/issues/3) OPEN هستند.

## ۴. شبکه افقی توانمندسازها و مرز استفاده

| گروه افقی (همه candidate) | اسناد پایه | پرسش باز و مانع انتقال ضمنی |
| --- | --- | --- |
| LX-IDENTITY | [۲۵](25-actors-channels-and-workspaces.md)، [۲۶](26-conceptual-information-structure.md) | اشتراک شخص، حق خواندن پرونده موتور دیگر نمی‌دهد |
| LX-KNOWLEDGE | [۲۷](27-shared-services-and-external-boundaries.md)، [۳۱](31-conceptual-experience-navigation-map.md) | حق محتوا/قواعد RXP، پول یا امتیاز فرضی نیست |
| LX-AI | [۱۹](19-business-quality-attributes-and-invariants.md)، [۲۷](27-shared-services-and-external-boundaries.md) | مدل، داده و حق تصمیم/آموزش هنوز تصویب نشده |
| LX-EVIDENCE | [۳۲](32-exceptions-and-human-decision-points.md)، [۴۱](41-operations-evidence-and-escalation-map.md) | مدرک و شواهد با اختیار انسانی و تصمیم متفاوت‌اند |
| LX-PARTNERS | [۳۴](34-partner-ecosystem-and-relationship-map.md)، [۳۸](38-partner-engagement-lifecycle.md) | فهرست شریک به معنای قرارداد یا فعال‌سازی نیست |
| LX-INSIGHTS | [۳۶](36-management-reporting-and-metric-candidates.md)، [۳۷](37-economic-flow-and-report-boundaries.md) | تعریف KPI، مجوز داده و روش تجمیع هنوز OPEN |
| LX-GOVERNANCE | [۴۲](42-business-governance-and-authority-map.md)، [۴۳](43-business-policy-and-change-versioning.md) | گیت توسعه با اختیار واقعی عملیات تجاری یکی نیست |

## ۵. ساختار هماهنگی بدون اختلاط

- **شواهد و درخواست‌ها:** فعالیت فیزیکی/اظهار کاربر → پرونده احتمالی بررسی؛ تصمیم و اجازه دسترسی فقط پس از قرارداد مربوط. [۳۰](30-business-interaction-and-handoff-map.md)، [۳۹](39-physical-digital-operations-map.md).
- **تصمیم و مسئولیت:** پیشنهاد → مدرک → بازبینی → صاحب اختیار واقعی → اثر مجاز، صرفاً توصیف تحلیلی؛ هیچ workflow واقعی تصویب نشده. [۴۲](42-business-governance-and-authority-map.md).
- **تغییر و تاریخ:** تعریف سیاست/قرارداد جدید الزاماً سابقه قبلی را بازنویسی نمی‌کند؛ **اثر دقیق هنوز باید با مدرک تصمیم‌گیری شود**. [۴۳](43-business-policy-and-change-versioning.md).
- **گزارش:** نمای Domestic و Export مستقل، تلفیق تنها در صورت قرارداد/روش معتبر آینده. [۳۶](36-management-reporting-and-metric-candidates.md)، [۳۷](37-economic-flow-and-report-boundaries.md).
- **کنترل تغییر نرم‌افزار:** RON-DEC-007 فرآیند Business → Technical → Product Backlog → Sprint → Code → Code Review → Stage → QA/Testing → Release Approval → Production → Monitoring → Improvement است؛ این سند تنها Business است.

## ۶. زمینه راهبرد و ذی‌نفعان — تکمیل نمای ساختاری v0.16

[تحلیل محیط/ریسک](49-strategic-environment-and-risk-structure.md) مدعیات PESTEL، SWOT و چرخه عمر سه **بازوی تحلیلی** در متن را به Domestic، Export و توانمندسازهای هوشمند وصل می‌کند. [رقابت/ذی‌نفعان](50-competition-stakeholder-and-positioning-structure.md) پنج نیروی پورتر، ماتریس Power–Interest و ادعاهای مقایسه برندها را در حد **فرض منبع و سؤال تحقیق** ثبت می‌کند. «سه بازوی چرخه عمر» **سه موتور اقتصادی مستقل نیست**؛ ساختار روناس همچنان دو موتور دارد. آمار ادعایی، تضمین‌های قیمت/تازگی و مقصدهای نمونه اعتبارسنجی یا تصویب نشده‌اند.

## ۷. وضعیت تحویل و رجوع به اقلام بی‌پاسخ

[دفتر مسائل باز ۴۷](47-open-structure-gaps-and-evidence-register.md) و [بسته بازبینی موکول ۴۸](48-structural-baseline-and-future-review-package.md) همراه نقشه حاضر خوانده شوند. 

**Conclusion:** STRUCTURE ASSEMBLED AS DRAFT — **NOT** proof of source completeness, Business approval, real contracts, authorized payment/export, Technical architecture or code readiness.
