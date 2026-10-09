# روناس — سیاست Business هوش کاملاً داخلی و اختصاصی با یادگیری تدریجی | RON-DEC-027

**Status: APPROVED STRATEGIC BUSINESS DIRECTION / TRAINING & TECHNICAL NOT AUTHORIZED**  
**Date:** 2026-10-09  
**Owner statement:** «برای هوش روناس ماباید کاملا داخلی و لختصاصی درست کنیم یک دیتاست اولیه بهش آموزش میدمی بعدا به مرور از زمان از داده ها ترین خواهد شد.»  
**Authority:** [RON-DEC-027](04-decisions-and-open-questions.md)، [حدود انسانی قبلی RON-DEC-015..021](52-domestic-continuous-digital-supervision-decisions.md)، [AI-first discovery & sources](63-ai-first-knowledge-and-training-readiness-proposal.md)، [استقلال موتور/حقوق داده](27-shared-services-and-external-boundaries.md).  
**Gate state:** [Domestic #2](https://github.com/mahdimarzooghi4-debug/Ronas/issues/2)، [Export #3](https://github.com/mahdimarzooghi4-debug/Ronas/issues/3)، [Finance #4](https://github.com/mahdimarzooghi4-debug/Ronas/issues/4) **OPEN**.

## ۱. آنچه مالک کسب‌وکار اکنون تصویب کرده است

1. **Ronas-owned and internally controlled intelligence:** هوش باید **اختصاصی برای روناس و تحت کنترل زیرساخت/داده/چرخه مدل روناس** باشد. آموزش و اجرای عملیاتی وابسته به **API سرویس AI خارجی** نیست و ارسال داده محرمانه به آن پیش‌فرض یا مجاز نیست. محل میزبانی، مالک حقوقی هر جزء، شکل استقرار و قراردادهای زیرساخت هنوز در Technical و بررسی حقوقی نیازمند تعیین‌اند.
2. **Initial training dataset:** پیش از اولین آموزش عملیاتی، یک **دیتاست اولیه با منشأ روشن و مجوز استفاده در Training** تشکیل/بازبینی شود؛ منظور تصمیم، **وجود دیتاست اولیه برای آموزش واقعی در زمان مجاز آینده** است، نه اینکه اکنون دیتاست آماده، برچسب‌گذاری‌شده یا دارای اجازه است.
3. **Progressive improvement over time:** بعداً داده‌های جدیدی که از فعالیت واقعی روناس و منابع مجاز به دست می‌آیند، در صورت واجد شرایط‌شدن از نظر کیفیت، حقوق و ارزیابی انسانی، به **نسخه‌های جدید دیتاست و چرخه‌های آموزش تکمیلی/مجدد** کمک کنند. بازآموزی تدریجی یک **قابلیت مطلوب محصول** است؛ زمان‌بندی، trigger، سطح خودکارسازی و روش الگوریتمی هنوز تصمیم نشده‌اند.
4. **No unconstrained live learning:** داده زنده، عکس خانوار، اسناد تجاری یا اصلاح/گزارش کاربران **خودکار و بدون رضایت/حق مشخص به Training نمی‌روند**. نتیجه آموزش صرفاً **نسخه کاندید** است؛ هیچ افزایش دقت ادعایی، تغییر مدل Production، کیفیت محصول، توصیه کشت معتبر یا مجوز مالی/قراردادی را خودکار فعال نمی‌کند.
5. **Human specialist and legal boundary:** حد تصمیم انسانی RON-DEC-015..021 و RON-DEC-025 پابرجاست. AI تنها **پیشنهادگر** برنامه کشت یا تطبیق شواهد است؛ متخصص واجد صلاحیت باید برنامه/استفاده مجدد از شواهد را تأیید کند و اثبات ایمنی خوراکی مستقل است. Export Lead به معنای مشتری/قرارداد نیست.

**نکته حقوقی مهم:** «هوش اختصاصی روناس» می‌تواند به مالکیت و کنترل **سامانه، داده‌های اختصاصی، آموزش و مدل مشتق‌شده** اشاره کند، اما این عبارت به‌تنهایی اثبات نمی‌کند که **تمام حقوق مالکیت وزن‌های پایه یا هر کتابخانه و منبع ثالث** متعلق به روناس شده‌اند. اگر مدل پایه مجاز از منبع ثالث به کار رود، مجوز و تعهدات آن پابرجاست. **انتخاب آموزش از صفر در برابر fine-tuning مدل پایه مجاز هنوز باز است.**

## ۲. زنجیره آتیِ داده و یادگیری روناس — مفهومی، نه معماری انتخاب‌شده

```text
Authorized Knowledge Sources / Ronas-Owned Consented Data
              |
              v
Rights, consent, origin, scope and quality checks
              |
              v
Expert-reviewed / policy-eligible learning records
              |
              v
Versioned INITIAL DATASET  ---> subsequent versioned datasets
              |                           ^
              v                           |
Candidate Training or Retraining    new permissioned & reviewed observations
              |
              v
Immutable/versioned candidate model & full lineage
              |
              v
Independent evaluation on held-out, permitted evidence
              |
              v
Expert / accountable human review
              |
              v
Explicit authorized promotion to active runtime
              |
              v
Monitored advisory use ---> validated feedback (not automatic promotion)
```

- **Knowledge source registry** و **پایگاه دانش** ممکن است برای استناد و retrieval مفید باشند، اما خودبه‌خود دیتاست آموزش وزن‌ها نیستند.
- **Training data ≠ Evaluation data**: قاعده جداسازی و جلوگیری از آلودگی داده باید در Technical و QA تعریف و آزموده شود.
- **Data reuse** between Domestic and Export: only with explicit scope/rights and independent review; shared model infrastructure is not a cross-engine data license.
- **Continuous learning** describes a planned controlled lifecycle; whether cycles are scheduled or manually triggered is OPEN. **Continuous** does *not* mean unrestricted background model self-modification.
- **Data minimization, correction, deletion and provenance** must not be defeated by model training. Retention periods and techniques for withdrawal/unlearning are not specified by this Business decision.

## ۳. اولین Dataset: برنامه گردآوری شواهد، بدون جعل داده یا الگوریتم

| پرونده | مشخصات لازم قبل از برچسب Training-eligible | وضعیت امروز |
| --- | --- | --- |
| **Domain goal** | انتخاب و محدودسازی وظیفهٔ اولین مدل/نمونه‌ها؛ محتوای آموزشی عمومی D0 با توصیه اختصاصی کشت D1 فرق دارد، پژوهش Export E0 نیز مستقل است | **OPEN — task not selected** |
| **Licensing / owner** | منشأ، حق مشخص استفاده برای آموزش، نسخه، هدف، صاحب حق و امکان نگهداری/حذف داده | **NOT VERIFIED for initial corpus** |
| **Scientific quality** | دانش قابل استناد/بومی برای محصول/اقلیم و بازبین متخصص حقیقی، نه خوداظهاری AI | **NOT VERIFIED** |
| **Initial examples** | نمونه سؤال/پاسخ یا مشاهده/برچسب وابسته به Task آینده، با نسخه و سابقه تصحیح | **NO APPROVED TRAINING DATASET** |
| **Independent evaluation** | مثال‌های جدا از Training، نمونه خطا/ابهام، معیار/قبولی قابل‌سنجش با رأی مرجع ذی‌صلاح | **NOT DEFINED / NOT APPROVED** |
| **Runtime deployment** | مدل/مجوز/اجرای واقعاً داخلی، هزینه و ظرفیت واقعی، مسئول ارتقای انسانی | **TECHNICAL NOT ADMITTED** |

**Allowed right now:** تحقیق و ثبت شناسنامه عمومی منابع/شرایط حقوق استفاده، مشخص‌کردن مسئله علمی و شواهد موردنیاز، و تهیه بسته محدود Business برای تصویب مستقل. **Not allowed right now:** دانلود انبوه داده دارای محدودیت برای Training، آموزش مدل واقعی با داده حساس، انتخاب قطعی مدل و GPU یا استقرار/معامله.

## ۴. تصمیمات اصلیِ هنوز باز — برای پرسش مستقیم از مالک

| Blocker | سؤال دقیق برای تصمیم آتی | چرا تصویب نشده؟ |
| --- | --- | --- |
| **AI-BL-01: meaning of proprietary** | **الف:** آموزش وزن‌های مدل از صفر و مالکیت کامل وزن‌های پایه، یا **ب:** میزبانی داخلی یک مدل open-weight مجاز و آموزش اختصاصی آن در زیرساخت روناس؟ | «کاملاً داخلی و اختصاصی» **هر دو را به‌طور قطعی تعیین نمی‌کند**؛ هزینه/زمان/حقوقشان متفاوت است. |
| **AI-BL-02: first learning task** | نخستین دیتاست برای کدام وظیفه؟ کشت و برنامه اختصاصی Domestic، محتوای آموزشی D0، پژوهش Export E0 یا ترکیب دارای تقسیم حقوقی؟ | RON-DEC-026 آماده‌سازی موازی D0/E0 را تصویب کرده، نه خودکار انتخاب نخستین وظیفه Training. |
| **AI-BL-03: real dataset & reviewer** | منبع واقعی داده‌ها، رضایت/مجوز استفاده برای Training، دسترسی به متخصص معتبر و Dataset اولیه چه باشد؟ | هیچ مجموعه داده و صلاحیت واقعی احراز نشده است. |
| **AI-BL-04: ongoing retraining gate** | بازآموزی با چه trigger/سیکل و چه سطحی از تأیید انسانی انجام شود؟ | کارفرما هدف یادگیری تدریجی را تصویب کرده، نه شیوه زمان‌بندی/خودکارسازی/حد پذیرش. |
| **AI-BL-05: infrastructure and economics** | ظرفیت میزبان/سخت‌افزار و بودجهٔ آموزش/ارزیابی و امنیت؟ | بدون benchmark و اختیار مالی، انتخاب سایز/GPU/میزبان ساختگی خواهد بود. |

**Recommendation awaiting owner response:** برای کمینه‌کردن هزینه و شروع سریع‌تر، **گزینه ب (open-weight با مجوز معتبر، دانلود/اجرای کاملاً داخلی و fine-tuning اختصاصی روی داده مجاز)** برای مطالعه گزینه مطلوبی است؛ اما تا اجازه کارفرما **این گزینه مصوب نیست و نه وزن، مدل، مجوز یا پشته فنی انتخاب نشده**. «آموزش از صفر» به معنی هزینه/داده/زمان بسیار بیشتر است و نیازمند امکان‌سنجی واقعی.

## ۵. اثر مصوبه بر گیت‌ها و Process مادر

**RON-DEC-027** فقط هدف AI داخلی و چرخه دیتاست/بازآموزی را در سطح Business تصویب کرد. RON-DEC-026 صرفاً آماده‌سازی D0/E0 را مجاز می‌داند. بدون قرارداد Scoped Business و شواهد معتبر، راه به Technical/Backlog/Sprint/Code باز نشده؛ PR #1 Draft، PR #6 HOLD و PR #8 Discovery Draft می‌مانند.

**Approved now:** sovereign internal AI direction; initial training dataset as necessary; controlled progressive retraining direction; explicit human model governance and decision boundaries.

**Still OPEN:** starting model from scratch vs adapting permitted base; actual dataset provenance/rights, task and data split; human reviewer; technical stack/infrastructure; model family/size; training algorithm and evaluation criteria; costs; actual Training Run; all three Business Gates #2/#3/#4.

**FINAL: STRATEGIC OWNER DECISION RON-DEC-027 REGISTERED — NO DATA INGESTION, TRAINING, TECHNICAL ADMISSION OR PRODUCTION AUTHORIZED.**
