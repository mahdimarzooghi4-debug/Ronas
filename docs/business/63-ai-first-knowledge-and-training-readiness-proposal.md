# روناس — نقشه آغازِ دانش و یادگیری اختصاصی AI از روز نخست | AI-FIRST DISCOVERY / NOT APPROVED

**Status: PROPOSED AI-FIRST BUSINESS / DATA / LEARNING GOVERNANCE; OWNER DECISIONS REQUIRED; NO TECHNICAL ADMISSION, TRAINING RUN, MODEL OR DATA INGESTION AUTHORIZED.**  
**Date of public research:** 2026-10-09. **Scope:** Domestic crop advisory and Export opportunity research; separate data rights and evaluations.  
## وضعیت پس از مصوبه RON-DEC-027 — ADDENDUM / 2026-10-09

**توجه:** بخش‌های تاریخی پایین در زمان نگارش این گزارش، همگی PROPOSED بودند؛ اکنون کارفرما با **RON-DEC-027** جهت‌گیری **هوش کاملاً داخلی و اختصاصی روناس، دیتاست اولیه برای Training و چرخه یادگیری/بازآموزی تدریجی از داده‌های واجد شرایط** را تصویب کرده است. [سند مصوب و حدود باز](64-ronas-internal-ai-progressive-learning-business-direction.md) مرجع جاری است. بخش‌های درباره گزینه «API خارجی»، «استقلال داده» یا «آموزش تدریجی» در جدول پرسش‌های تاریخی نباید به‌عنوان وضعیت بازِ جهت‌گیری مصوب خوانده شوند؛ **انتخاب آموزش از صفر در برابر وزن پایه مجاز با اجرای داخلی، وظیفه نخست، داده/مجوز، متخصص، مدل، زیرساخت، هزینه و trigger آموزش هنوز OPEN است**. هیچ Training Run/Technical Gate با این مصوبه اجرا نشده است.

**This is not RON-DEC-027.** User asked: «هر مانعی که وجود داره از من بپرس و اگر به دانشی نیاز داری خودت از روی اینترنت پیدا ... تا بشه از اول هوش روناس ترین کنیم.» Thus the proposal researches open sources and gathers business-level owner blockers without deciding on their behalf.  
**Ronas baseline:** [RON-DEC-015..021 human-approved crop plans](04-decisions-and-open-questions.md), [RON-DEC-022..026 strategy, gates and D0/E0 evidence priority](04-decisions-and-open-questions.md), [AI and data business boundaries](27-shared-services-and-external-boundaries.md), [domain and data concepts](26-conceptual-information-structure.md), [D0](59-d0-noncommercial-domestic-education-business-packet.md), [E0](60-e0-export-opportunity-research-business-packet.md), [external official sources already screened](62-d0-e0-official-source-screening-and-usage-rights.md).

## ۱. تفکیک دانش، داده و آموزش — پیشنهاد معماری‌پذیری، نه Technical

| لایه پیشنهادی | هدف | مدرک لازم برای ورود داده | کاری که هنوز مجاز نیست |
| --- | --- | --- | --- |
| **A — Source Registry / Knowledge Review** | شناسایی منابع علمی/داده‌ای/حقوقی، نسخه و تاریخ، کشور/اقلیم/محصول، محدودیت/سطح اطمینان، تاریخ بازبینی متخصص، شروط استفاده | لینک/صاحب حق/نسخه/دامنه مجاز و مرور علمی | برداشت کل محتوا از اینترنت یا استفاده تجاری/آموزش مدل بدون بررسی حق |
| **B — Domain Knowledge Base (candidate)** | دانش مستند برای آموزش عمومی D0، و در آینده پیشنهاد کشت D1 یا تحقیق بازار E0، با ارجاع به منبع و امکان اصلاح | حق استفاده/اقتباس/نمایش برای مورد مصرف، اعتبار علمی متناسب با ایران | توصیه قطعی کشت، تشخیص بیماری یا گواهی سلامت صرفاً از یک مقاله |
| **C — Permissioned Learning Data (candidate)** | ذخیره جداگانه نمونه‌های دنیای واقعی یا منابع دارای اجازه استفاده برای آموزش، هر مورد با منشأ، هدف مجاز، وضعیت رضایت، بازبین و وضعیت کیفیت | داده واقعی مجاز یا مجموعه دارای شرایط روشن؛ رضایت اختصاصی در موارد لازم؛ بازبینی تخصصی | انتقال خودکار تصاویر/اطلاعات خانوار به Dataset؛ کپی خودکار پرونده Export به Training |
| **D — Independent Evaluation (candidate)** | آزمون سؤال و پاسخ مبتنی بر منبع، موارد ابهام/عدم قطعیت، اعتبار توصیه، سناریوی خطا، عدم اختلاط Train/Eval و خطاهای حساس | مجموعه مستقل و بازبینی انسان واجد صلاحیت؛ تعریف وظیفه و معیار قابل اندازه‌گیری | ادعای دقت یا معیار PASS ساختگی |
| **E — Model Learning and Promotion (candidate)** | انتخاب مدل پایه مجاز، امکان مقایسه retrieval با fine-tuning روی داده مجاز، آموزش تکمیلی کنترل‌شده و نسخه‌بندی | حقوق وزن‌های مدل/داده، سخت‌افزار و هزینه واقعی، نمونه کافی، baseline/evaluation، مصوبه Technical و گیت‌های مراحل بعد | آموزش مدل بزرگ از صفر به‌عنوان پیش‌فرض، مدل/Stack/GPU ساختگی، آپدیت خودکار Production، تصمیم مالی/QC خودکار |

**Proposed working principle:** از امروز می‌توان *پژوهش و ثبت مشخصات منابع* را آغاز کرد، اما گردآوری Dataset، دانلود انبوه/بازنشر داده‌های دارای محدودیت، Training Run، انتخاب مدل و پیاده‌سازی به **گیت‌های جداگانه و تأییدهای مشخص** نیاز دارند. **RAG/retrieval** به معنی آموزش وزن مدل نیست. نوع نهایی استفاده از پایگاه دانش، انتخاب Technical مستقل است.

## ۲. یافته‌های جدید از منابع رسمی و طبقه‌بندی مجوز

| شناسه | منبع/لینک رسمی | ارزش بالقوه برای روناس | آنچه از منبع فهمیده شد و مرز حقوقی/علمی |
| --- | --- | --- | --- |
| **AI-SRC-01** | [FAO AGROVOC Access](https://www.fao.org/agrovoc/index.php/access)؛ [AIMS access/license](https://aims.fao.org/standards/agrovoc/access-agrovoc) | واژگان، مفاهیم و روابط کشاورزی در قالب RDF/SKOS و API؛ نامزد استانداردسازی واژگان دانش/برچسب‌ها | **این منبع طبقه‌بندی/اصطلاحات است نه نسخه صحیحِ درمان گیاه یا برنامه کشت محلی**. AIMS مالکیت و CC BY IGO 3.0 را برای شش زبان رسمی FAO شرح می‌دهد؛ حقوق زبان‌های دیگر ازجمله هر برچسب فارسی باید در سطح ناشر بررسی شود. حتی برای شش زبان، متاداده/شرط استفاده و انتساب پیش از reuse بررسی شوند. |
| **AI-SRC-02** | [NASA POWER API](https://power.larc.nasa.gov/docs/tutorials/service-data-request/api/)؛ [Data services](https://power.larc.nasa.gov/docs/services/)؛ [NASA Earthdata general use guidance](https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy) | اقلیم تاریخی/ناحیه‌ای و سناریوهای تحقیق شرایط کشت، **نه داده خانه یا سنسور محلی** | NASA POWER داده اقلیمی رایگان جهانی ارائه می‌کند، اما وضوح مکانی و بازنگری داده‌ها محدودیت دارند؛ برای هر محصول/داده دقیق، دسترسی، کیفیت و مجوز اختصاصی باید بررسی شود. **داده شبکه‌ای معادل دمای باغچه یا فضای داخلی یک منزل نیست؛ نباید خودکار برای توصیه اختصاصی کافی تلقی شود.** |
| **AI-SRC-03** | [FAO home garden publications](https://www.fao.org/4/x3996e/x3996e25.htm)؛ [FAO copyright and permissions](https://www.fao.org/publications/about-fao-publishing/permissions/en)؛ [FAO terms](https://www.fao.org/contact-us/terms/) | مواد مبنای پژوهش برای دانش آموزشی D0 و نامزد مرور متخصص در D1 | دسترسی عمومی و نقل/تحقیق با ترجمه/اقتباس/انتشار محصول یا Training یکسان نیست؛ حقوق اثر، عکس و بخش ثالث جدا. **هیچ مجوز بازنشر/آموزش برای روناس اخذ نشده است.** |
| **AI-SRC-04** | [FAOSTAT database terms](https://www.fao.org/contact-us/terms/db-terms-of-use/en) | داده آماری تولید برای پژوهش ظرفیت، بدون نتیجه‌گیری درباره هر تأمین‌کننده | قاعده عمومی CC BY 4.0 همراه با شرایط تکمیلی FAO (ازجمله استفاده تبلیغاتی و استثناهای ثالث)؛ **قانون هر Dataset و استفاده تجاری خاص باید بازبینی شود.** |
| **AI-SRC-05** | [UN Comtrade data use](https://uncomtrade.org/docs/policy-on-comtrade-data-use/)؛ [Re-dissemination](https://uncomtrade.org/docs/re-dissemination-of-data/) | مجموعه کاندید پژوهش تقاضا/تجارت E0، فقط پس از تعریف HS/محصول–مقصد/دوره | منبع استفاده داخلی، ازجمله استفاده داخلی در مدل AI، را از **بازتوزیع اصل داده در محصول یا برنامه سودمحور** متمایز می‌کند و برای صورت‌های مختلف قیود/استثنا دارد؛ **برای مدل و سرویس نهایی روناس بررسی حقوقی مورد استفاده لازم است؛ مجوز تجاری عام فرض نشود**. |
| **AI-SRC-06** | [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)؛ [Gen AI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf) | چارچوب مرجع داوطلبانه برای منشأ/حقوق داده، ارزیابی، آزمون، کنترل خطا، نظارت و سیاست‌های انسانی | **راهنمای سنجش ریسک است نه مجوز قانونی، استاندارد الزام‌آور ایران، یا معیار دقت عددی از پیش تصویب‌شده.** |
| **AI-SRC-07** | [Transformers fine-tuning guide](https://huggingface.co/docs/transformers/training)؛ [Creative Commons AI legal primer](https://creativecommons.org/2025/05/15/understanding-cc-licenses-and-ai-training-a-legal-primer/) | فهم تفاوت pretraining-from-scratch و fine-tuning مدلِ از پیش‌آموزش‌دیده؛ حقوق استفاده از محتوای دارای مجوز | Fine-tuning بر Dataset وظیفه‌محور معمولاً محاسبه/داده بسیار کمتری از آموزش مدل بزرگ از صفر می‌خواهد؛ **این انتخاب نهایی مدل، مجوز استفاده از هر متن اینترنتی، یا حکم حقوقی قطعی درباره Training نیست**. |

**Scope of actual research in this turn:** صفحات رسمی اسناد/شرایط منبع و guidance بررسی شدند. **No data extracted as machine-training corpus, no Persian crop diagnosis corpus curated, no real labeled observations, no Iranian agronomist sign-off, no trained model.** In particular public access ≠ universal training license. Research on a legal question does not replace Iran-specific legal advice.

## ۳. ترتیب پیشنهادی برای اینکه AI از روز نخست «قابلیت یادگیری» داشته باشد

1. **Stage 0: Knowledge-governance readiness (Business):** تصمیم صاحب کسب‌وکار درباره AI-first scope، سیاست استقلال/محل اجرای داده، رضایت و حقوق استفاده، منابع علمی و مسئول تخصصی. انتخاب چند دسته دانش آغازین و داوری حقوق منابع؛ «منبع شناخته‌شده» را از «مجاز برای Dataset» جدا کنیم.
2. **Stage 1: Evidence-led information architecture (after scoped Business admission):** تعریف قرارداد منبع، موضوع/برچسب‌های کشاورزی، نسخه/صلاحیت/متاداده و شاخص‌بندی در گام Technical؛ هیچ تکنولوژی/DB/API از این سند انتخاب نمی‌شود.
3. **Stage 2: Reviewed samples & evaluation:** شواهد واقعی/مجوزدار و نمونه‌های بازبینی‌شده را از ابتدا با هویت منبع، هدف، نسخه و وضعیت رضایت نگه داریم؛ مجموعه ارزیابیِ مستقل از آموزش ساخته شود. **برنامه کشت اختصاصی، کیفیت خوراکی یا تصمیم تجاری بدون مجوز انسانی معتبر نمی‌شود**.
4. **Stage 3: Candidate model learning (only after explicit Technical and relevant gates):** ارزیابی رویکرد پایگاه دانشِ مستند، و در صورت کفایت داده/مجوز، مدل ازپیش‌آموزش‌دیده مجاز و آموزش تکمیلی. مدل نهایی بر اساس شواهد، مجوز و زیرساخت واقعی انتخاب شود؛ آموزش از صفر اگر کارفرما آن را ترجیح دهد نیازمند پروژه/بودجه/محاسبات مستقل است.
5. **Stage 4: Human-governed quality and Production:** مقایسه نمونه‌ها، گزارش خطا و عدم قطعیت، بازبینی متخصص، ارزیابی مستقل و تصویب انسان برای ارتقا؛ هیچ مدل یا قانون یادگیری به‌صورت خودکار وارد Production نشود.

**Critical distinction:** شروع روزاولِ دانش/نسخه‌بندی/قابلیت تشکیل Dataset **قابل برنامه‌ریزی** است؛ آموزش واقعی وزن‌های مدل پیش از حق داده/نمونه/گیت مجاز نیست. همچنین داده تصاویر/خانه Domestic یا اسناد مشتری Export بدون مبنای حقوقی مستقل مشترک نمی‌شوند.

## ۴. موانع واقعاً وابسته به تصمیم صاحب روناس — یک بسته سؤال راهبردی، نه سؤال‌های خرد

| Blocker | یک تصمیم یا ورودی لازم از مالک | پیشنهاد کارشناسی *در انتظار تصویب* |
| --- | --- | --- |
| **O1 — تعریف «از اول Train»** | آیا منظور **AI-first از روز نخست و fine-tuning تدریجی مدل پایه** است یا **pretraining مدل بزرگ از صفر**؟ | AI-first knowledge + reviewed datasets + independent evaluation از ابتدا؛ **pretrained licensed foundation model با fine-tuning پس از شواهد**؛ از صفر نه پیش‌فرض |
| **O2 — قلمرو قابلیت‌های نخست** | اولویت دانش/ارزیابی AI در **Domestic** (آموزش/کشت با متخصص)، **Export** (تحقیق/بازار) یا هر دو به‌صورت هم‌زمان؟ | هر دو مسیر دانش با دیتاست/حقوق مستقل؛ ابتدا خروجی **research/advisory**، D0 و E0 همچنان Business PREPARATION ONLY |
| **O3 — مالکیت و محل اجرای مدل/داده** | آیا سیاست مطلوب **مدل و داده اختصاصی/اجرای داخلی بدون ارسال داده حساس به API خارجی** است، یا اجازه استفاده از خدمات خارجیِ صریحاً مجاز هم مدنظر است؟ | مدل و داده خصوصی Ronas-owned، اجرا در زیرساخت تحت کنترل پروژه؛ انتخاب مدل/سخت‌افزار/هاست بعد از گیت |
| **O4 — داده‌های واقعی و حقوق یادگیری** | آیا امکان دسترسی به **نمونه‌های دارای حق استفاده/رضایت اختصاصی برای آموزش** و **متخصص صلاحیت‌دار برای برچسب‌گذاری و ارزیابی** وجود دارد؟ اگر نه، آیا آماده‌سازی مسیر جذب آن‌ها تصویب می‌شود؟ | هیچ Household/Export data خودکار Training-eligible نشود؛ رضایت آموزش از رضایت ارائه خدمت جدا باشد؛ در آغاز نمونه علمی/آزمایشی غیرشخصی فقط برای ارزیابی داخلی با منشأ معتبر |
| **O5 — بومی‌سازی موضوع** | بازار/اقلیم یا شهر Domestic و نامزد محصولات کشاورزی اولیه و، برای Export، حوزه اولیه محصول–مقصد برای **تعریف تحقیق**؛ یا تصویب اینکه تا فراهم‌شدن شواهد باز بمانند | اگر هنوز انتخاب نشده‌اند، تحقیق دسته‌های دانش مقدماتی بدون رتبه‌بندی ساختگی محصول–مقصد ادامه یابد؛ Dataset محلی و تست‌های علمی محصول‌محور منتظر Scope واقعی |

**Other blockers tracked, not forced as micro owner decisions now:** حق بازنشر FAO/AGROVOC زبان فارسی، مقررات ایران/بخش کشاورزی، مجوز Trade datasets، کارشناسان واقعی، مدل/وزن و مجوز آن، منابع GPU/بودجه، قرارداد حریم خصوصی، معیار ارزیابی ایمنی و تغییر نسخه، استاندارد QC قانونی، FIN-001..007، زیرساخت استقرار و مسئول Release. خودِ تحقیق منبع و بررسی حقوق/فنی قابل پیگیری است؛ انتخاب/تأیید مستلزم اختیار و شواهد است.

## ۵. پیشنهاد تصمیم یکجای بعدی

**AI-FIRST-01 — PROPOSED / NOT OWNER-APPROVED**:

> «از ابتدای مسیر Ronas، ثبت دانش مستند، حقوق منبع، داده مجاز و یادگیری/ارزیابی نسخه‌دار را در طراحی Business و بعداً Technical قرار دهیم. برای Domainهای Domestic و Export مجموعه‌های مستقل نگه داریم، AI را پیشنهادگر و انسان متخصص را صاحب تصمیم نگه داریم. آموزش واقعی مدل با داده دارای حق و نمونه بازبینی‌شده، بعد از پذیرش گیت و انتخاب فنی مجاز انجام شود؛ هیچ انتقال داده یا ارتقای خودکار Production نباشد. انتخاب مدل، زیرساخت، معماری، بودجه، محصول/مقصد، صاحب حقوق داده و سیاست API/خودمیزبانی تا پاسخ‌های O1..O5/مدارک باز می‌ماند.»

در صورت تصویب یا اصلاح توسط کارفرما، تصمیم مستقلی از نوع RON-DEC-027 با استثناهای دقیق ثبت شود. **در وضعیت فعلی، این متن فقط یک پیشنهاد است و RON-DEC-027 نباید خودکار ثبت شود.**

**FINAL: KNOWLEDGE SOURCE RESEARCH RECORDED; AI-FIRST STRATEGY PROPOSED ONLY; TRAINING CORPUS, MODEL, TECHNICAL GATES, CODE, FINANCE/OPERATIONS ALL NOT AUTHORIZED.**
