# روناس — نقشه شواهد دیتاست اولیه و چرخه یادگیری تحت کنترل | AI Dataset Evidence Blueprint

**Status: BUSINESS PREPARATION / DRAFT EVIDENCE REQUEST — NOT APPROVED DATASET, TASK OR TECHNICAL CONTRACT**  
**Date:** 2026-10-09  
**Subsequent owner decision RON-DEC-028 — APPROVED BUSINESS MODEL PATH:** گزینه **ب** برای مدل پایه **Open-Weight با مجوز معتبر، اجرای کاملاً داخلی و Fine-tuning اختصاصی روناس** تصویب شد؛ مسیر آموزش وزن‌ها از صفر انتخاب‌شده نیست. **AI-BL-01 RESOLVED at Business level؛** مجوز واقعی مدل نامزد، Task نخست، Dataset معتبر، معیار، متخصص، هزینه، GPU، طراحی فنی و همه گیت‌ها همچنان بازند. [دفتر مصوبه](04-decisions-and-open-questions.md) / [سیاست جاری](64-ronas-internal-ai-progressive-learning-business-direction.md).  

**Decision authority:** [RON-DEC-027](04-decisions-and-open-questions.md) *already APPROVED* the strategic requirement for fully internal Ronas-specific AI, a legitimate initial dataset, later versioned retraining and explicit human Production promotion. This document **does not create a new owner decision**.  
**Related:** [canonical internal-AI policy 64](64-ronas-internal-ai-progressive-learning-business-direction.md)، [AI-first discovery 63](63-ai-first-knowledge-and-training-readiness-proposal.md)، [source and usage-rights screening 62](62-d0-e0-official-source-screening-and-usage-rights.md)، [D0](59-d0-noncommercial-domestic-education-business-packet.md)، [E0](60-e0-export-opportunity-research-business-packet.md)، [Finance/Legal](61-finance-legal-evidence-workstreams-for-d0-e0.md).  
**Gate:** Domestic #2, Export #3, Finance #4 **OPEN**. No Technical/Code/Training/Deployment authorization.

## ۱. محدوده دقیق این پیش‌نویس

این سند فقط **نقشه گردآوری شواهد** برای امکان تشکیل دیتاست آموزشی آینده است. تصمیم RON-DEC-027 تغییر نکرده و اکنون با **RON-DEC-028، مدل پایه Open-Weight با مجوز معتبر و Fine-tuning کاملاً داخلی** به‌عنوان مسیر Business انتخاب شده است؛ مدل پایه/نسخه/حق تجاری و استفاده/تغییر/توزیع واقعی هنوز باید تأیید شوند. هیچ مدل، وزن، فرمت، GPU، الگوریتم، نرخ، آستانه پذیرش، بازبین حقیقی، دیتاست واقعی یا وظیفه اول انتخاب نشده است.

- **D0 (Domestic):** محتوای عمومی آموزش کشاورزی غیرتجاری فقط *نامزد بررسی* برای Task/Examples آتی است؛ D0 هرگز اجازه توصیه اختصاصی برنامه کشت، جمع‌آوری تصویر/پرونده خانوار برای Training یا انتشار محتوای شخص ثالث بدون حق را ایجاد نمی‌کند.
- **E0 (Export):** پژوهش عمومی فرصت محصول–مقصد فقط *نامزد بررسی* است؛ رتبه‌بندی یا اشاره به بازار، اثبات مشتری/قرارداد/تطبیق قانون مقصد/سود نیست. هیچ داده محرمانه شریک، صادرکننده یا خانواده Domestic به Training انتقال نمی‌یابد.
- **D1 شخصی‌سازی برنامه کشت** خارج از D0 است و حتی در آینده تصمیم نهایی آن به متخصص واجد صلاحیت تعلق دارد؛ **E1** و قرارداد/تجارت واقعی خارج از E0 است. تصویب آماده‌سازی موازی D0/E0 به‌معنای تصویب Training هم‌زمان یا مدل واحدِ مصرف‌کننده داده مشترک نیست.

## ۲. دفتر نامزدهای منبع؛ هیچ ردیف مجوز Training تأییدشده ندارد

| کاندیدا / مرجع اولیه | کاربرد پژوهشی احتمالی، نه حق استفاده Training | وضعیت واقعی برای روناس |
| --- | --- | --- |
| [FAO Home Garden / Education](62-d0-e0-official-source-screening-and-usage-rights.md) | فهرست موضوعات آموزش کشت خانگی و سؤالات داوری علمی D0 | **SOURCE SCREENED / ترجمه، اقتباس، نشر و Training RIGHT NOT CLEARED** |
| [FAO AGROVOC](63-ai-first-knowledge-and-training-readiness-proposal.md) | واژگان/رده‌بندی چندزبانه و نگاشت اصطلاحات، با بررسی حقوق مشارکت‌کنندگان هر زبان | **SOURCE SCREENED / حق داده‌برداری و مشتقات Training به‌ازای ماده خاص NOT CLEARED** |
| [NASA POWER](63-ai-first-knowledge-and-training-readiness-proposal.md) | متغیرهای اقلیمی برای مطالعه بافت و سنجش اعتبار زمانی/مکانی، نه تشخیص وضعیت واقعی خانه | **SOURCE SCREENED / dataset-specific use-rights, geography, uncertainty and fitness NOT VERIFIED** |
| [FAOSTAT](62-d0-e0-official-source-screening-and-usage-rights.md) | زمینه آمار تولید در سطح کلان Export، نه ظرفیت تأمین‌کننده واقعی | **SOURCE SCREENED / rights, data vintage, third-party conditions and task fitness NOT VERIFIED** |
| [UN Comtrade](62-d0-e0-official-source-screening-and-usage-rights.md) | روند تجارت پس از تعریف مشخص کالا/HS/مقصد/دوره و بازبینی آماری | **SOURCE SCREENED / training and redistribution rights NOT CLEARED; no product/destination chosen** |
| [WITS, ITC Trade Map, WTO ePing](62-d0-e0-official-source-screening-and-usage-rights.md) | مقایسه پژوهشی یا پیگیری اعلان‌ها، بدون تلقی اعلان به‌عنوان گواهی حقوقی الزام قطعی | **SOURCE SCREENED / rights, access and task fitness NOT VERIFIED** |
| [NIST AI RMF](63-ai-first-knowledge-and-training-readiness-proposal.md) | چارچوب مطالعه حکمرانی و ریسک، **نه** منبع مثال‌های کشاورزی یا دیتاست Train | **REFERENCE ONLY; NOT TRAINING CORPUS** |

**قاعده صدور اجازه:** خواندن، ارجاع، دسترسی API/CSV، انتشار محتوا، بازنشر داده و **آموزش وزن مدل/ایجاد مشتق** حقوق مستقل‌اند؛ نباید آن‌ها را معادل دانست. وجود CC، دسترسی عمومی، صفحات ناشر یا امکان دانلود به‌تنهایی به معنای تأیید حقوق برای مورد استفاده مشخص روناس نیست. بررسی حقوقی واقعی به‌ازای **نسخه منبع × محتوا/فیلد × روش اخذ × هدف استفاده × نحوه توزیع خروجی** لازم است.

## ۳. شناسنامه پیشنهادی هر مجموعه داده / Evidence Ledger

هر ردیف در آینده برای یکی از Domainهای مستقل ثبت شود؛ فیلد زیر **الزامِ شواهد مورد درخواست** است و نه Schema نرم‌افزار تصویب‌شده:

| گروه شواهد | داده لازم برای تصمیم‌گیری درباره اجازه Training |
| --- | --- |
| شناسه و منشأ | Evidence ID، ناشر/صاحب حق، URL/منشأ واقعی، عنوان، نسخه/تاریخ برداشت، تغییرات و مدرک قابل بازیابی |
| حد استفاده | Domain/Task، نوع داده (محتوای علمی، مشاهده، گزارش، تصویر، داده تجاری)، حساسیت/حق دسترسی و هدف دقیق Training/Evaluation/Reference |
| حقوق و رضایت | متن/مبنای اجازه و محدودیت‌ها؛ امکان استخراج، تبدیل، آموزش مدل، ذخیره، انتشار خروجی، محدودیت قلمرو/زمان و شخص ثالث؛ برای داده شخصی **رضایت/مبنای مستقل Training** |
| کیفیت و صلاحیت | اعتبار موضوعی، منطقه/اقلیم/محصول، عدم‌قطعیت، تعارض منابع، مرجع بازبین متخصص واقعی و تصمیم قابل ممیزی |
| دسته‌بندی یادگیری | پیشنهاد نمونه Input/Expected Outcome/Label، منشأ برچسب، قاعده رسیدگی به خطا/ابهام و موارد ناشناخته؛ **هیچ Label با حدس AI معتبر نمی‌شود** |
| جداسازی Evaluation | منشأ و نسخه بخش ارزیابی، عدم اشتراک موارد وابسته/خانوار/سند/قرارداد با Training، بررسی نشت محتوا و شاخص‌های ارزیابی **پس از تعریف Task** |
| حقوق پسینی | حدود اصلاح/حذف/انصراف، اثر بر نسخه‌های داده و مدل، نگهداری و محل شواهد، و محدودیت ردیابی اطلاعات محرمانه |
| مالک تصمیم | مرجع حقوقی/علمی بررسی‌کننده، تاریخ و نتیجه VERIFIED / REJECTED / NOT VERIFIED، شناسه مصوبه Scope مربوط؛ **تا احراز، NOT TRAINING-ELIGIBLE** |

**هیچ ردیف مجوزی امروز Verified نیست.** نمونه‌های مصنوعی یا پرسش‌های دست‌نویس بدون پشتوانه علمی/حقوقی نیز به‌طور پیش‌فرض «دیتاست واقعی معتبر» یا «ارزیابی مستقل» نیستند.

## ۴. انتخاب وظیفه نخست و تمایز کیفیت برای دو مسیر

| مسیر نامزد | خروجی پژوهشی قابل تعریف پس از تصمیم Business | شاهد ضروری قبل از پذیرفتن Task و برچسب |
| --- | --- | --- |
| D0 عمومی | مطالعه Q/A آموزشیِ **غیرشخصی** و پاسخ مستند به محتوای مجاز | حق آموزش با مواد، دامنه موضوع/اقلیم واقعی، صلاحیت بازبین علمی، موارد «پاسخ نده/ارجاع»، تفکیک پاسخ عمومی از توصیه ویژه خانوار |
| E0 پژوهشی | مطالعه تحلیل مستند/محدود **محصول–مقصد** با ارجاع منبع و تاریخ | تعریف محصول/HS/مقصد/دوره، سازگاری منابع و حقوق Training، بررسی تفاوت آمار و مقررات، راستی‌آزمایی انسانی نتایج، «سرنخ ≠ معامله» |
| D1 آتی (خارج از D0) | پیشنهاد برنامه کشت برای ارزیابی متخصص، نه تصمیم خودکار | شواهد محیط واقعی، حقوق داده خانوار، اعتبار منطقه/محصول، معیار متخصص و مرزهای ایمنی؛ **گیت جدا** |

**AI-BL-02 OPEN:** مالک هنوز مشخص نکرده اولین Training Run کدام Task را هدف بگیرد؛ RON-DEC-026 فقط اولویت *تهیه موازی پرونده‌های D0 و E0* است.

## ۵. چرخه یادگیری تحت کنترل؛ Workflow مفهومی، نه طراحی فنی

1. **Source & permission intake:** معرفی شواهد با حد دسترسی مشخص، بدون دریافت انبوه اطلاعات حساس/دارای حق نامشخص.
2. **Legal, consent, provenance & scientific review:** بررسی مستقل صاحب‌حق و متخصص؛ رد یا تعلیق موارد بی‌مجوز، ناهمگون، تاریخ‌گذشته یا نامطمئن.
3. **Versioned eligible records:** تنها موارد پذیرفته‌شده در Scope مرتبط نامزد نسخه دیتاست می‌شوند؛ داده Domainها خودکار با هم ادغام نمی‌شود.
4. **TRAINING dataset version** و **INDEPENDENT EVALUATION dataset version:** انتشار هویت/منشأ/ترکیب و شواهد جداسازی. نسخه ارزیابی نباید از همان مثال‌ها، تکرار محتوا یا مورد متعلق به همان Household/Contract که در Training است بهره بگیرد؛ قرارداد دقیق ضدنشت در Technical/QA تعریف می‌شود.
5. **Training/retraining run (future):** مجوز مستقل اجرا، نسخه ورودی/پارامتر/مصنوعات برای ردیابی. اجرای واقعی تنها پس از Gate و قرارداد فنی؛ **روش کلان Fine-tuning مدل پایه مجاز مصوب است، اما جزئیات روش و مجوز/مدل مشخص هنوز OPEN**.
6. **Candidate artifact:** نتیجه موفق آموزش صرفاً نامزد، با هویت و تاریخچه تغییر، نه Production.
7. **Independent evaluation & safety/domain review:** بررسی صحت علمی، خطاهای خطرناک، داده گمشده/مناقشه‌دار، پایداری زمانی/منطقه‌ای، جدایی Domain، حقوق داده و دامنه استفاده؛ معیارها و حدود قبولی هنوز تعریف/تصویب نشده‌اند.
8. **Explicit accountable human approval:** ارتقای هر نسخه نیازمند تصمیم ثبت‌شده انسانی است؛ عدم‌وجود اجازه، نتیجه مبهم یا ارزیابی ناقص = **عدم تغییر نسخه فعال**.
9. **Monitored advisory runtime & feedback:** خروجی توصیه‌ای، بازخورد **ممیزی‌شده**؛ داده عملیاتی یا نظر کاربر بدون حقوق/بازبینی دوباره به Training نمی‌رود. تغییر الگوریتم، بازآموزی دوره‌ای و rollback باید در Technical/Gate بعدی قرارداد شوند.

**تفاوت‌های حفاظت‌شده:** Knowledge source ≠ training corpus؛ داده علمیِ قابل مشاهده ≠ دارای مجوز مدل‌سازی؛ Training ≠ Evaluation؛ Candidate ≠ Production؛ خروجی هوش ≠ تأیید متخصص؛ پیشنهاد صادراتی ≠ قرارداد/سود؛ مشاهده Domestic ≠ داده قابل آموزش Export.

## ۶. مانع‌ها و گیت قابل حسابرسی؛ بدون ساختن قبول/رد عددی

| مانع | وضعیت | مدرک/تصمیم لازم در آینده |
| --- | --- | --- |
| AI-BL-01 روش کلان مالکیت/آموزش | **RESOLVED — RON-DEC-028 OPTION B APPROVED** | مدل پایه Open-Weight مجاز + Fine-tuning کاملاً داخلی؛ **مدل/نسخه/حقوق واقعی و تأیید Technical هنوز OPEN** |
| AI-BL-02 Task اول آموزش (D0/E0/D1 یا تفکیک) | **OWNER DECISION OPEN** | Scope قابل تفکیک و قرارداد علمی/حقوقی وظیفه |
| AI-BL-03 دیتاست دارای حق Training و بازبین تخصصی | **EVIDENCE NOT VERIFIED** | حق واقعی منبع/رضایت، داده/نمونه‌های معتبر، مدارک صلاحیت و نتیجه بازبینی |
| AI-BL-04 cadence/trigger و سطح خودکارسازی بازآموزی | **POLICY NOT SET** | ضابطه، اختیار انسانی، شروط توقف و پیوند به مستقل‌بودن Evaluation |
| AI-BL-05 هزینه/زیرساخت/ظرفیت | **TECHNICAL & FINANCE GATES OPEN** | مطالعه تطبیقی با شواهد پس از انتخاب مسیر و Task؛ بدون حدس GPU، نرخ یا بودجه |

**خروجی مجاز کنونی:** تکمیل فرم شواهد/حقوق، اعتبارسنجی دامنه علمی منابع و تدوین قرارداد محدود Business برای بررسی. **خروجی غیرمجاز:** اعلام Dataset-READY، Data ingestion واقعی برای Training، انتخاب مدل/پشته/میزبان، اجرای Training/Evaluation/Production، برداشت داده خانوار/اسناد Export بدون مجوز، یا عبور از گیت‌های #2/#3/#4.

**Verdict:** RON-DEC-027 STRATEGY APPROVED; EVIDENCE BLUEPRINT PREPARED ONLY; FIRST TASK & EXACT BASE MODEL/LICENSE OPEN; BUSINESS MODEL PATH B APPROVED; NO VERIFIED TRAINING DATA; NO EXECUTION AUTHORIZED.


**تکمیل نقشه Task/Evaluation (غیرمصوب):** [پرونده ۶۷: دو نامزد D0/E0 برای نخستین وظیفه و طراحی شواهد ارزیابی مستقل](67-first-ai-learning-task-and-independent-evaluation-business-packet.md). تصمیم AI-BL-02 هنوز OPEN؛ نمونه‌های سناریو، Dataset/Label واقعی یا معیار قبولی ایجاد نشده‌اند.
