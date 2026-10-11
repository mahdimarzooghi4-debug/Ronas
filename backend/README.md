# Ronas: signed-token backend foundation

## تحویل خواندنی و ممیزی‌پذیرِ ساختار پیشنهاد AI داخلی به کارشناس — LOCAL/TEST

از پرونده DEMO تخصیص‌یافته کارشناس کشاورزی `/agronomy/assigned-drafts/{ref}` اکنون پیوندی به `/agronomy/assigned-drafts/{ref}/internal-plan-proposal` وجود دارد؛ API فقط GET نیز `/api/v1/agronomy/assigned-drafts/{ref}/internal-plan-proposal` است. بدون تزریق صریح نمونه ساختاری AI، عبارت **«هنوز هیچ پیشنهادی وجود ندارد»** نمایش داده می‌شود؛ نه اینکه از فیلدهای `null` برنامه کشت ساخته شود. در تستِ دارای نمونه ساختاری، نسخه پرونده، نسخه و digest ورودی از **مرجع مستقل آزمایشی** و تخصیص فعلی کارشناس باید کاملاً تطبیق داشته باشند و دفتر ممیزی همان تراکنش را کنترل می‌کند. فقط شناسه مراحل فرضی به کارشناس دارای دسترسی نشان داده می‌شود، نه اطلاعات خانوار، digest مدل/منبع یا متن دستور کشت. هیچ AI واقعی اجرا نشده، تأیید متخصص، توصیه، مرحله نظارت یا برنامه معتبر ایجاد نشده است. خروجی فنی `STRUCTURE_ONLY_UNREVIEWED` / `NOT_AUTHORED` است. مرجع تخصصی و داده‌های واقعی بعداً **داخلی خود روناس** تدارک دیده می‌شوند، با حفظ الزام رضایت و صلاحیت واقعی.

مستند: [internal-ai-agronomy-handoff-contract.md](internal-ai-agronomy-handoff-contract.md). آزمون‌های مستقل جدید در `tests/test_agronomy_workspace.py`. گیت‌های Business بازند؛ رابط دوم یا پنل جدیدی اضافه نشده است.


## مالکیت داخلی برنامه کشت — قرارداد آفلاین بدون پذیرش علمی

طبق جهت‌گیری Business **RON-DEC-033** (در Draft PR #1)، طراحی علمی/فنی برنامه کشت و ابزار نظارت در مسئولیت خود **روناس** است و نیازی به انتخاب پیمانکار بیرونی برای ادامه آماده‌سازی ندارد. الگوی RON-DEC-015..021 ثابت است: اطلاعات رضایتمندانه خانوار ← پیشنهاد اختصاصی توسط AI داخلی ← احراز کفایت داده و بررسی/تأیید صریح **متخصص واجدصلاحیت داخلی روناس** ← گزارش‌دهی براساس مراحل همان برنامه تأییدشده؛ اصلاح اطلاعات، پیشنهاد نسخه جدید و تأیید مجدد را لازم می‌کند.

قرارداد فنی آزمایشی `internal_cultivation_plan_contract.py` تنها **ساختار و پیوند دقیق نسخه پرونده، نسخه ورودی، digest مدل/منبع علمی، پیشنهاد و مراحل آن** را بررسی می‌کند و هیچ مدل، محصول، برنامه، زمان‌بندی یا دستور کشت تولید نمی‌کند. حتی نمونه دارای پیوند ساختاری صحیح، `STRUCTURE_ONLY_UNREVIEWED` و `NOT_ACCEPTED` باقی می‌ماند؛ تأیید علمی، رضایت واقعی، اجرای AI، مراحل نظارت، توصیه اجرایی، معامله و پذیرش خودکار وجود ندارد. API و UI عملیاتی اضافه نشده‌اند. مستند: [internal-cultivation-proposal-contract.md](internal-cultivation-proposal-contract.md)؛ آزمون‌ها در `tests/test_internal_cultivation_plan_contract.py`. گیت Domestic #2 همچنان باز است.


## نمای یکپارچه آماده‌سازی شخصی خریدار/فروشنده تجهیزات — LOCAL/TEST

در همان محیط مشترک، مسیر `/domestic-partners/my-preparation` و API صرفاً GET در `/api/v1/domestic-partners/my-preparation` فقط پیش‌نمای‌های مجاز **همان حساب امضاشده** را در کنار هم نشان می‌دهند. برای دو نقش `local_buyer` و `equipment_seller` کنترل جاری مجوز **مستقل** انجام می‌شود؛ لغو دسترسی یکی به دیگری منتقل نمی‌شود و نقص/خطای مرجع مجوز، کل پاسخ را بدون افشای داده جزئی 503 می‌کند. جایگاه‌های نامشخص صرفاً از فیلدهای `null` نسخه‌های DEMO مشتق می‌شوند، **نه معیار الزامی پذیرش یا آمادگی Business**. هیچ پیوند واقعی بین خریدار، خانوار و فروشنده تجهیزات ایجاد نمی‌شود؛ وضعیت ارزیابی تجاری `NOT_EVALUATED` باقی می‌ماند و ارائه داده، تطبیق، پیشنهاد، معامله و پرداخت فعال نیستند. صفحه‌های شخصی پیشین و نقش‌ها حفظ شده‌اند.

قرارداد: [domestic-partner-preparation-overview-contract.md](domestic-partner-preparation-overview-contract.md). پوشش ۹ آزمون جدید در `backend/tests/test_domestic_partner_self_preview.py`. گیت‌های Business و محدودیت دو محیط برقرارند.


## تجربه خریدار محلی و فروشنده تجهیزات در محیط مشترک — LOCAL/TEST

دو نقش موجود `local_buyer` و `equipment_seller` اکنون با تزریق صریح نمونه آزمایشی و دسترسی جاریِ مستقلِ هر نقش، در `/workspace/local_buyer` و `/workspace/equipment_seller` به پیش‌نمای شخصی می‌رسند: `/local-buyer/my-preview` و `/equipment-seller/my-preview`. APIهای فقط GET: `/api/v1/local-buyer/my-preview` و `/api/v1/equipment-seller/my-preview`. همه فیلدهای درخواست خرید یا کالا/موجودی تجهیزات **نامشخص (`null`)** است. این جایگاه‌ها فرم ثبت، معیار پذیرش، قیمت، پیشنهاد، معامله یا تأیید علمی نیستند. نقش امضاشده Keycloak و مجوز فعلی دقیق هر نقش/موضوع/نمونه برای هر درخواست بررسی می‌شود؛ هیچ مجوزی میان نقش‌ها منتقل نمی‌شود. لغو دسترسی با توکن معتبر قدیمی نیز مؤثر است، قطع مرجع دسترسی خطای 503 بسته ایجاد می‌کند، و حالت عادی بدون تزریق پیش‌نمایی ندارد.

قرارداد: [domestic-partner-self-preview-contract.md](domestic-partner-self-preview-contract.md). آزمون‌های اختصاصی: `backend/tests/test_domestic_partner_self_preview.py` (۱۵ سناریوی آزمایشی). همچنان فقط دو محیط کاربری وجود دارد و گیت‌های Business بازند.


## تاریخچه نسخه‌ها و ناوبری پرونده پژوهش صادرات — LOCAL/TEST

در پنل مدیریت واحد روناس، اپراتور `export_ops` با مجوز **جاری و مستقل پرونده** می‌تواند از صف فیلترشده `/admin/export/research` به جزئیات همان پرونده وارد شود و بدون گم‌کردن فیلتر و موقعیت صفحه‌بندی بازگردد. مسیر جدید `/admin/export/research/drafts/{ref}/versions` و API خواندنی `GET /api/v1/admin/export/research/drafts/{ref}/versions` فقط شماره نسخه‌های از پیش ثبت‌شده DEMO را با ممیزی الحاقی نمایش می‌دهند، نه محتوای تاریخی، تغییرات فرضی یا تأیید مجوز منبع. فهرست مراحل فنی در جزئیات با توضیح فارسی و فقط از رویدادهای ثبت‌شده نمایش داده می‌شود. دسترسی دوباره در هر مشاهده بررسی می‌شود و با لغو مجوز، صفحه بعدی دیگر قابل خواندن نیست.

قرارداد: [export-research-version-navigation-contract.md](export-research-version-navigation-contract.md). ۱۱ آزمون جدید در `backend/tests/test_export_research_queue.py` برای تاریخچه، حریم پرونده، لغو مجوز، ممیزی، تغییرات غیرمجاز، نشست و ناوبری. محصول/کشور/HS/گزارش/خریدار/قیمت/قرارداد واقعی ساخته نشده‌اند؛ گیت‌های Business همچنان بازند.


## فیلتر پیگیری پرونده‌های خانوار — LOCAL/TEST

در همان محیط مشترک کاربران، خانوار می‌تواند فهرست پرونده‌های DEMO متعلق به خود را بر اساس مرحله فنی **ثبت‌شده** فیلتر کند: `ALL`، `UNREQUESTED`، `EVIDENCE_REVIEW_REQUESTED`، `HUMAN_RESPONSE_RECORDED`. این فیلتر به `GET /api/v1/domestic/household-intake/my-drafts/technical-progress` و نمای فارسی `/` اضافه شده است؛ پیمایش بعدی فیلتر را حفظ می‌کند. نقش امضاشده `household` و مالکیت دقیق پرونده پیش از فیلتر و صفحه‌بندی بررسی می‌شوند. شناسه خانوار دیگر، جزئیات شاهد/بازبین و شمارش پنهان برنمی‌گردد. خطا و خراب‌شدن تاریخچه یا ممیزی به صورت بسته (503) مدیریت می‌شود.

پیگیری فنی صرفاً مشاهده است؛ حتی پاسخ انسانی نیز به معنی مجوز طرح کشت، رضایت واقعی یا تأیید علمی نیست. نمای کارشناس کشاورزی و مسیر تاریخچه نسخه‌ها همچنان مستقل از مالکیت شخص دیگرند. مستند: [household-progress-filter-contract.md](household-progress-filter-contract.md). آزمون‌های جدید: `backend/tests/test_owned_household_technical_status.py`.


## صف فیلترشونده کارشناس کشاورزی — فقط LOCAL/TEST

در محیط مشترک کارشناس کشاورزی، `/workspace/agronomy_expert` و API خواندنی `GET /api/v1/agronomy/assigned-drafts` اکنون فیلتر `technical_state` دارند: `ALL` (پیش‌فرض)، `UNREQUESTED`، `EVIDENCE_REVIEW_REQUESTED` و `HUMAN_RESPONSE_RECORDED`. صفحه‌بندی و لینک‌های فارسی وضعیت فیلتر را حفظ می‌کنند. فقط مرحله فنی واقعاً ثبت‌شده پس از احراز نقش امضاشده و تخصیص معتبر **جاری** هر پرونده نمایش داده می‌شود؛ بدون شمارش پرونده‌های پنهان یا انتشار مراجع خصوصی. وضعیت «پاسخ فنی ثبت‌شده» تأیید علمی یا مجوز طرح کشت نیست؛ داده‌های کشت همچنان نامشخص، و عملیات Business غیرفعال است.

قرارداد: [agronomy-shared-workspace-contract.md](agronomy-shared-workspace-contract.md)؛ شش سناریوی رگرسیون جدید در `backend/tests/test_agronomy_workspace.py`. هیچ پنل جدید، عملیات نوشتن، داده واقعی یا تصمیم Business اضافه نشده است.


## پیش‌نمای شخصی تأمین‌کننده صادرات — فقط LOCAL/TEST

در محیط مشترک کاربران روناس، نقش امضاشده `export_supplier` فقط با نمونه آزمایشی مشخص و دسترسی جاری خود می‌تواند در `/workspace/export_supplier` و `/export-supplier/my-preview` جایگاه‌های خالی اطلاعات تأمین‌کننده را ببیند. API صرفاً خواندنی: `GET /api/v1/export-supplier/my-preview`. همه فیلدهای هویت، محصول، ظرفیت، زمان دسترسی، تأسیسات و مجوز `null` هستند؛ هیچ اظهاری ثبت یا تأیید نمی‌شود و معامله/خریدار/قرارداد وجود ندارد. هیچ پنل سوم یا دسترسی به پرونده داخلی Export ایجاد نشده است.

قرارداد: [export-supplier-self-preview-contract.md](export-supplier-self-preview-contract.md). آزمون‌ها: `backend/tests/test_export_supplier_self_preview.py` (۱۵ سناریوی آفلاین). وضعیت گیت‌های Business بدون تغییر است.


## صف پژوهش صادرات با فیلتر و صفحه‌بندی در پنل مدیریت واحد — LOCAL/TEST

به‌جای گسترش زیرساخت استعلام شواهد، قابلیت عملیاتی‌نمای **مرور پرونده‌های پژوهش ساختگی** برای اپراتور صادرات اضافه شده است. از `/admin` به `/admin/export/research` می‌رسد؛ می‌تواند فقط پرونده‌های Export دارای مجوز فعال خودش را با فیلتر مراحل موجود بررسی فنی (`ALL`، `UNREQUESTED`، `EVIDENCE_REVIEW_REQUESTED` و `HUMAN_RESPONSE_RECORDED`) و صفحه‌بندی مشاهده کند و صفحه جزئیات هر پرونده را باز کند. API: `GET /api/v1/admin/export/research/cases`.

دفتر SQLite محلی در **یک تراکنش** تاریخچه و مجوز جاری را بررسی، موارد مجاز را پیش از فیلتر/صفحه‌بندی محدود و فقط موارد افشاشده را ممیزی می‌کند. هیچ کشور، محصول، HS، قیمت، خریدار، نتیجه تحقیق یا حق استفاده از منبع ساخته نمی‌شود؛ فیلتر وضعیت فنی به معنی تأیید گزارش نیست. برنامه پیش‌فرض و همه درخواست‌های نوشتن همچنان غیرفعال‌اند.

قرارداد: [export-research-queue-contract.md](export-research-queue-contract.md). آزمون‌ها: `backend/tests/test_export_research_queue.py` (۱۷ آزمون آفلاین شامل جداسازی پرونده، لغو مجوز، فیلتر، رگرسیون حریم خصوصی و شکست ممیزی).


## خط زمانی مشاهده‌شده بررسی فنی پرونده Domestic — فقط LOCAL/TEST

دو صفحه موجود `/my-drafts/{ref}` خانوارِ مالک و `/agronomy/assigned-drafts/{ref}` کارشناس دارای تخصیص جاری، از `technical_timeline` در قرارداد مشترک `ronas.domestic.preparation-preview.v1` استفاده می‌کنند. این فهرست فقط رویدادهای واقعاً ثبت‌شده `TECH_REVIEW_REQUESTED` و `TECH_HUMAN_RESPONSE_RECORDED` را به ترتیب revision با توضیح ثابت فارسی نمایش می‌دهد؛ رویداد آینده، زمان، هویت طرف مقابل، مرجع خصوصی، تصمیم علمی و تأیید طرح کشت حدس زده نمی‌شود. عنوان معنایی و `aria-label` در HTML حفظ شده است.

قرارداد: [domestic-observed-progress-timeline-contract.md](domestic-observed-progress-timeline-contract.md). ۶ آزمون جدید در `backend/tests/test_agronomy_workspace.py` برای رد مرحله جعلی، مشاهده مرحله ثبت‌شده، فیلتر حریم خصوصی، دسترسی مستقل و توضیح فارسی. همه این داده‌ها فقط DEMO هستند و ثبت واقعی کشت/رضایت/تأیید هنوز مسدود است.


## نمای هماهنگ پیش‌نیازهای کشت برای خانوار و کارشناس — فقط LOCAL/TEST

در دو صفحه موجود `/my-drafts/{ref}` (فقط مالک خانوار) و `/agronomy/assigned-drafts/{ref}` (فقط کارشناس دارای تخصیص معتبر و جاری)، جایگاه‌های نمایشی محصول، مساحت، آب، خاک و موقعیت از قرارداد واحد `ronas.domestic.preparation-preview.v1` ارائه می‌شوند. همه مقادیر `null` و وضعیت طرح کشت `NOT_AUTHORED` هستند؛ نه معیار کفایت اطلاعات تعیین شده، نه رضایت واقعی و صلاحیت حرفه‌ای احراز شده و نه برنامه علمی/عملیاتی ساخته شده است. ثبت مرجع پاسخ انسانی در بررسی فنی هرگز این نتیجه را تغییر نمی‌دهد.

**یکسان بودن ساختار نمایش به معنای یکسان بودن دسترسی نیست.** هر سمت احراز هویت، مالکیت یا تخصیص دقیق خود و رویداد ممیزی جداگانه در تراکنش مستقل دارد؛ شناسه، تخصیص، شواهد و اطلاعات خصوصی طرف مقابل فاش نمی‌شود. هشدار «رضایت واقعی احراز نشده» در هر دو صفحه حفظ شده است. قرارداد: [domestic-shared-preparation-preview-contract.md](domestic-shared-preparation-preview-contract.md). ۸ آزمون جدید در `backend/tests/test_agronomy_workspace.py` برای تطابق وضعیت‌ها، جداسازی نقش‌ها، تغییر مجوز، هشدار HTML، مراحل بررسی و fail-closed هنگام خرابی تاریخچه ثبت شده‌اند.


## فضای کار کارشناس کشاورزی در محیط مشترک — فقط LOCAL/TEST

کارشناس با نقش امضاشده `agronomy_expert` تنها در صورت **تخصیص صریحِ نسخه‌بسته پرونده DEMO و تأیید جاری دسترسی همان پرونده** می‌تواند در `/workspace/agronomy_expert` فهرست پرونده‌های تخصیص‌یافته و در `/agronomy/assigned-drafts/{ref}` نمای اطلاعات اولیه را ببیند. API فقط خواندنی `GET /api/v1/agronomy/assigned-drafts` و `GET /api/v1/agronomy/assigned-drafts/{ref}` با Keycloak معتبر فعال می‌شود. نقش عملیات داخلی به‌اشتباه مجوز کارشناس تلقی نمی‌شود؛ API فراداده نقش هم فقط در صورت اتصال صریح `ASSIGNED_SYNTHETIC_AGRONOMY_DRAFTS` را اعلام می‌کند.

داده‌های محصول، مساحت، آب، خاک و موقعیت فعلاً `null` هستند. نه طرح کشت واقعی تولید شده، نه صلاحیت حرفه‌ای، رضایت خانوار یا بررسی علمی تأیید شده است. ممیزی خواندن در همان تراکنش و رد فوری دسترسی پس از غیرفعال‌شدن کنترل تخصیص آزمایشی اجرا می‌شود. **هیچ سرویس واقعی یا پنل سومی ساخته نشده است.**

قرارداد: [agronomy-shared-workspace-contract.md](agronomy-shared-workspace-contract.md). آزمون‌ها: `backend/tests/test_agronomy_workspace.py` (۱۸ آزمون). محدوده‌های Business و سیاست‌های واقعی حرفه‌ای/کشاورزی باید در آینده به‌صورت جداگانه و انسانی تصویب شوند.


## فضای پژوهش صادرات در پنل مدیریت واحد — فقط LOCAL/TEST

اپراتور `export_ops` که برای یک پرونده `EXPORT` از قبل مجوز معتبر و تخصیص دقیق دارد، اکنون از فهرست پرونده‌های مدیریت روناس به صفحه فارسی `/admin/export/research/drafts/{ref}` می‌رسد. API خواندنی `GET /api/v1/admin/export/research/drafts/{ref}/workspace` از همان دفتر فنیِ نسخه‌بسته و ممیزی‌شده، اطلاعات حداقلی پرونده، مرجع `DEMO` و وضعیت بررسی را نمایش می‌دهد. هیچ پنل مستقل پژوهشگر صادرات، کشور/محصول/HS اختراعی، یافته قطعی بازار، مجوز منبع، خریدار یا قرارداد ایجاد نمی‌شود؛ همه پرچم‌های تأیید و عملیات واقعی خاموش‌اند.

تراکنش واحد، مجوز فعال پرونده، نسخه‌های واقعیِ داده آزمایشی و رویداد ممیزی خواندن را کنترل می‌کند؛ لغو تخصیص فوراً دسترسی را می‌بندد. صفحه و API در برنامه پیش‌فرض فعال نیستند. قرارداد: [export-research-workspace-contract.md](export-research-workspace-contract.md). ۱۴ آزمون جدید به `backend/tests/test_technical_review_worklist.py` افزوده شد. این کار اولویت را به مسیر اصلی پژوهش E0 برمی‌گرداند و هیچ گیت Business را نمی‌بندد.


## تاریخچه نسخه‌های پرونده خانوار — در همان محیط مشترک کاربران، فقط LOCAL/TEST

در فهرست `/` خانوار، کنار پرونده‌های متعلق به همان هویت امضاشده، لینک `/my-drafts/{ref}/versions` اضافه شده است. API متناظر `GET /api/v1/domestic/household-intake/my-drafts/{ref}/versions` فقط نسخه‌های **واقعاً از پیش Seedشده DEMO** را بازمی‌گرداند؛ نسخه غایب، تاریخ، اصلاح واقعی، رضایت داده یا تأیید کارشناس حدس زده نمی‌شود. دسترسی مالک با یک تراکنش و ممیزی الحاقی مستقل از مجوز کارکنان کنترل می‌شود؛ پرونده دیگران، Export و اطلاعات محرمانه نمایش داده نمی‌شوند. تنها با Keycloak و دفتر آزمایشی که صریحاً تزریق شده باشد فعال است؛ مسیر جزئیات بررسی فنی مستقل می‌ماند و در دفتر پایه به اشتباه فعال نمی‌شود.

قرارداد: [household-owned-version-history-contract.md](household-owned-version-history-contract.md). ۱۲ آزمون جدید و یک اصلاح آزمون رگرسیون: `backend/tests/test_owned_household_drafts.py` و `backend/tests/test_owned_household_technical_status.py`. عملیات ثبت یا اصلاح واقعی خانوار هنوز مجاز نشده است؛ گیت‌های Business مربوط باز مانده‌اند. این مرحله تمرکز توسعه را از زیرساخت جزئی احراز شواهد به تجربه اصلی خانوار برگردانده است.


## مرز اتصال به مراجع احراز واقعی — فعلاً غیرفعال و fail-closed

قرارداد `ronas.authority.request.v1` شناسه فنی استعلام‌های `ORIGIN`، `SOURCE_RIGHTS` و `REVIEWER_QUALIFICATION` را با نسخه سند Business، ارجاع اصلی و رویداد دقیق درخواست پیوند می‌دهد. اثرانگشت SHA-256 فقط برای ثبات این پیوند **داخلی** است و به معنی امضای معتبر مرجع یا اصالت سند نیست. هیچ سرویس، سازمان، اعتبارنامه، آدرس شبکه، پاسخ مورداعتماد یا سیاست پذیرش تعیین و فعال نشده است.

حتی اگر آداپتور سازگار یا پاسخ ظاهراً امضاشده به قرارداد داده شود، **ارسال به مرجع خارجی و پذیرش پاسخ بدون شرط رد می‌شود**. مسیر صرفاً خواندنی `GET /api/v1/admin/gate-evidence/{domain}/authority-connectors` فقط در برنامه اختیاری Keycloak با دفترهای آزمایشی یکسان فعال است و همه ۱۹ مورد را با وضعیت `NO_AUTHORITY_APPROVED` نشان می‌دهد. هویت و مرجع خصوصی استعلام از API خارج نمی‌شوند؛ هیچ مسیر POST/بارگذاری/تأیید وجود ندارد.

قرارداد و پیش‌نیازهای اتصال آینده: [business-gate-authority-connector-contract.md](business-gate-authority-connector-contract.md). آزمون‌ها: `backend/tests/test_gate_authority_connector_boundary.py` (۱۵ آزمون آفلاین). حق استفاده از داده، صلاحیت واقعی بازبین و تصمیم Business باید ابتدا توسط مرجع انسانی مجاز تصویب شوند؛ گیت‌های #2، #3 و #4 همچنان بازند.


## ماتریس یکپارچه پیگیری فنی شواهد — فقط LOCAL/TEST

داده‌های دو دفتر مستقلِ ارجاع شواهد و استعلام منشأ/حقوق استفاده/صلاحیت بازبین، اکنون برای نقش امضاشده هر حوزه از **یک تراکنش واحد SQLite** خوانده می‌شوند. نمای تازه در همان مدیریت واحد `/admin/gate-evidence/{domain}/readiness` و API صرفاً خواندنی `GET /api/v1/admin/gate-evidence/{domain}/readiness-matrix` قرار دارد؛ تنها وقتی دفترهای صریحاً تزریق‌شده، نسخه منبع و نشست معتبر Keycloak یکسان باشند. `governance` می‌تواند فراداده عمومی Business را مشاهده کند، اما بدون نقش خود حوزه به دفترهای فنی دسترسی نمی‌گیرد.

حتی پس از دریافت مرجع پاسخ هر سه استعلام، **اصالت منشأ، حق استفاده، صلاحیت بازبین، پذیرش شواهد و تأیید Business همچنان احرازنشده/مسدود** می‌مانند. خواندن تاریخچه، یکپارچگی آن را بررسی می‌کند اما رویداد ممیزیِ خواندنِ مجزا ثبت نمی‌کند. قرارداد: [business-gate-readiness-matrix-contract.md](business-gate-readiness-matrix-contract.md). آزمون‌ها: `backend/tests/test_gate_readiness_matrix.py` (۱۵ سناریو). هیچ مدرک واقعی، منبع خارجی، پرداخت، تصمیم یا پنل تازه‌ای ایجاد نشده است.


## استعلام مستقل منشأ، حقوق منبع و صلاحیت بازبین — فقط LOCAL/TEST

دفتر الحاقی `SqliteSyntheticAuthorityEnquiryLedger` به **همان دفتر فنی ارجاع شواهد** متصل است و برای هر یک از ۱۹ مورد شواهد سه موضوع جداگانه `ORIGIN`، `SOURCE_RIGHTS` و `REVIEWER_QUALIFICATION` دارد. یک اپراتور آزمایشی می‌تواند مرجع درخواست `DEMO` را ثبت کند و بازبین مستقلِ صریحاً مجاز فقط مرجع یک پاسخ فنی `DEMO` را ثبت می‌کند. پاسخ، احراز مدرک یا حقوق منبع نیست و هیچ مرجع واقعی/خارجی فراخوانی نمی‌شود.

رابط مدیریت واحد فقط در صورت تزریق صریح همان دفتر مشترک، وضعیت خواندنی استعلام‌ها را نمایش می‌دهد: `GET /api/v1/admin/gate-evidence/{domain}/authority-enquiries`. تمام نتایج `NO_TRUSTED_EXTERNAL_AUTHORITY` و `admission_allowed=false` / `business_gate_passed=false` باقی می‌مانند. هیچ endpoint عمومی برای درخواست، پاسخ، بارگذاری یا تأیید ایجاد نشده است. سامانه پیش‌فرض این نما را فعال نمی‌کند.

قرارداد فنی: [business-gate-authority-enquiry-contract.md](business-gate-authority-enquiry-contract.md). آزمون‌ها: `backend/tests/test_gate_authority_enquiry.py` (۱۸ سناریو). قبل از اتصال شواهد واقعی باید مرجع قانونی/اجرایی و معیار احراز منبع، حق استفاده و صلاحیت انسانی با تصمیم صریح صاحبان اختیار تعیین شود؛ این بسته هیچ‌یک را حدس نمی‌زند.


## پیش‌شرط پذیرش شواهد: احراز منشأ، حقوق استفاده و صلاحیت بازبین — فقط LOCAL/TEST

نمای خواندنی جدید `GET /api/v1/admin/gate-evidence/{domain}/admission-preflight` برای هر یک از ۱۹ مورد شواهد گیت‌های Business نشان می‌دهد که **اصالت منشأ، حقوق منبع/رضایت و صلاحیت واقعی بازبین هنوز احراز نشده‌اند**؛ هیچ شاهدی پذیرفته و هیچ گیتی PASS نمی‌شود. تنها با تزریق صریح دفتر آزمایشی ارجاع شواهد و احراز هویت Keycloak فعال است. در پنل مدیریت واحد، هشدار «کنترل پذیرش مسدود» نمایش داده می‌شود و هیچ فرم ثبت، بارگذاری مدرک یا تأیید اضافه نشده است.

یک کنترل داخلیِ آفلاین امکان تطبیق بایت‌های مشخصاً `DEMO` با هش SHA-256 **اعلام‌شده** را دارد؛ نتیجه تطبیق حتی در صورت مثبت بودن، اثبات منشأ، حقوق قانونی یا مجوز بازبین نیست و در وضعیت عملیاتی/پایگاه داده ثبت نمی‌شود. استفاده از فایل واقعی یا داده شخصی در این کنترل ممنوع است. قرارداد: [business-gate-admission-preflight-contract.md](business-gate-admission-preflight-contract.md). آزمون‌ها: `backend/tests/test_gate_evidence_preflight.py` (۱۴ مورد). تعیین مراجع معتبر، معیارها و فرآیند پذیرش واقعی همچنان نیازمند تصمیم‌های انسانی Business است.


## ارجاع فنی شواهد Business برای بررسی انسانی — فقط LOCAL/TEST

یک دفتر الحاقی و مستقل برای ثبت **ارجاع ساختگی** به ۱۹ مورد شواهد Domestic، Export و Finance اضافه شده است. ثبت‌کننده با نقش معتبرِ حوزه خودش می‌تواند فقط مرجع `DEMO` و هش SHA-256 **اعلام‌شده و احرازنشده** را در قرارداد داخلی ثبت کند. بازبین جداگانه تنها با اجازه صریح `trusted_review_authorizer` می‌تواند مرجع یک یادداشت فنی را ثبت کند؛ ثبت‌کننده حق بررسی همان ارجاع را ندارد.

تفاوت وضعیت‌ها صریح است: `NO_REFERENCE`، `REFERENCE_RECORDED` و `HUMAN_NOTE_RECORDED`. حتی حالت سوم **مدرک تأییدشده، حقوق داده/منبع احرازشده یا PASS گیت نیست**. نه فایل واقعی یا داده شخصی دریافت می‌شود و نه مسیر عمومی POST/تأیید ساخته شده است. تنها مسیر GET اختیاری `/api/v1/admin/gate-evidence/{domain}/technical-handoff` و نمایش وضعیت در همان پنل مدیریت موجود فعال می‌شوند، آن هم فقط با تزریق جداگانه دفتر آزمایشی و نشست معتبر. اجرای پیش‌فرض بدون آن است.

قرارداد کامل: [business-gate-technical-handoff-contract.md](business-gate-technical-handoff-contract.md). ۱۹ آزمون جدید: `backend/tests/test_gate_evidence_handoff.py`. Business Gateهای #2/#3/#4 باز هستند و برای هر شاهد واقعی، حقوق منبع، منشأ قانونی و صلاحیت شخص بازبین باید جداگانه توسط صاحبان اختیار تعیین و مستند شود.


## تشخیص تغییر اسناد شواهد گیت — فقط محیط آزمایشی

برای نمای خواندنی گیت‌های Business، وجود نام سند کافی نیست: اکنون محتوای دقیق دو سند مرجع با شناسه Git Blob ثبت‌شده، و هر ۱۹ وضعیت و شناسه ردیف با نسخه تاریخی مقایسه می‌شوند. حذف، دست‌کاری یا تغییر این اسناد باعث پاسخ کنترل‌شده `503 PINNED_BUSINESS_SOURCE_UNAVAILABLE` و مخفی‌شدن پیوندهای قدیمی گیت در صفحه مدیریت می‌شود؛ سایر قابلیت‌های مستقل پنل باقی می‌مانند. این کنترل **وضعیت جاری PR #1 یا Issueهای #2/#3/#4 را از GitHub نمی‌خواند** و به‌هیچ‌وجه رأی گیت یا تأیید شواهد نیست.

نسخه Git و رویه تطبیق انسانی هر تغییر در [business-gate-evidence-contract.md](business-gate-evidence-contract.md) مستند شده‌اند. آزمون‌های خطای نسخه/هویت فایل در `backend/tests/test_business_gate_evidence.py` اجرا می‌شوند. هر تغییر Business باید ابتدا مستقل بررسی و مستند شود، نه اینکه سامانه به‌طور خودکار وضعیت مدرک، صلاحیت یا گیت را تغییر دهد.


## نمای مدیریتی شواهد گیت‌های Business — فقط نسخه‌بسته و خواندنی

در **همان پنل واحد `/admin`**، فهرست شواهد Domestic (شش شناسه D1-B)، Export (شش شناسه E0-B) و Finance (هفت شناسه FIN) با تفکیک نقش امضاشده نمایش داده می‌شود. نقش `governance` تنها اجازه مرور فراداده بازِ هر سه حوزه را دارد و به پرونده‌های اشخاص یا تراکنش‌ها مجوز نمی‌گیرد. مسیرهای GET `/api/v1/admin/gate-evidence` و `/api/v1/admin/gate-evidence/{domain}` فقط در نمونه محلی با نشست Keycloak تزریق‌شده فعال هستند؛ داده از سند رسمی Business PR #1 با SHA `5492690e91955e64353824ffa4ec3250286fdf68` به‌صورت **نسخه‌بسته و صریحاً غیرزنده** خوانده/ثبت شده است.

هر مورد، شناسه، برچسب و وضعیت همان سند را دارد؛ همه شواهد در این برنامه `verified_here=false` هستند و گیت‌ها در **آن نسخه** OPEN بوده‌اند. **هیچ گیتی با CI یا نمایش UI به PASS نمی‌رود**؛ صاحب اختیار، حقوق داده، مدل مالی و شواهد واقعی هنوز باید مستقل احراز شوند. لینک‌های منبع و Issueهای #2/#3/#4 برای بررسی انسانی ارائه می‌شوند. قرارداد: [business-gate-evidence-contract.md](business-gate-evidence-contract.md)؛ ۱۷ آزمون: `backend/tests/test_business_gate_evidence.py`. هیچ سند خصوصی، تصمیم، قیمت، بودجه یا جریان مالی جدید ایجاد نشده است.


## فضای کار نقش‌محور در محیط مشترک کاربران و همکاران — فقط LOCAL/TEST

پنج نقش مصوب `household`، `local_buyer`، `agronomy_expert`، `equipment_seller` و `export_supplier` اکنون در محیط **مشترک** `/` لینک فضای کار خواندنی خود را دارند. `/workspace/{role}` فقط با نشست معتبر Keycloak و نقش امضاشده قابل مشاهده است؛ نقش ناموجود و نقش متعلق به دیگری به شکل یکسان `404` می‌گیرند. این یک مسیر در همان محیط کاربران است، نه پنل سوم یا خدمت جدید عملیاتی.

مسیرهای `GET /api/v1/me/user-workspaces` و `GET /api/v1/me/user-workspaces/{role}` فقط نقش‌های فعلی امضاشده، برچسب نمایشی و قابلیت‌های **خواندن داده ساختگی که واقعاً به برنامه تزریق شده‌اند** را برمی‌گردانند. برای سایر نقش‌های همکار هیچ دسترسی پرونده‌ای جعل یا از نقش استنتاج نمی‌شود. فعالیت Business برای تمام نقش‌ها `NOT_OPERATIONAL` است؛ خرید، فروش، تأیید، مجوز کارشناس و صادرات واقعی فعال نیستند. مسیرهای جدید فقط در نسخه آزمایشی با `BrowserOIDC` فعال می‌شوند؛ اجرای پیش‌فرض همچنان بدون این رابط است.

قرارداد: [shared-user-workspaces-contract.md](shared-user-workspaces-contract.md). آزمون‌ها: `backend/tests/test_shared_user_workspaces.py` (۱۶ سناریو). گیت‌های Business داخلی #2، صادرات #3 و مالی #4 باز و PRها Draft باقی می‌مانند.


## نمای یکپارچه پیگیری خانوار — فقط LOCAL/TEST

مسیر GET آزمایشی `/api/v1/domestic/household-intake/my-drafts/technical-progress` برای خانوار احرازشده، نسخه پرونده‌های Domestic متعلق به همان خانوار و **وضعیت فنی مشاهده‌شده** هر پرونده را در یک فهرست صفحه‌بندی‌شده بازمی‌گرداند. بک‌اند فقط با تزریق صریح دفتر `SqliteSyntheticHumanReviewLedger` فعال می‌شود و کل صفحه را از یک تراکنش ممیزی‌شده می‌سازد. در همان محیط `/` کاربران و همکاران، کنار هر پرونده وضعیت فنی به فارسی نمایش داده می‌شود و مرجع پاسخ انسانی هرگز معادل پذیرش یا تأیید طرح کشت نیست.

تنها داده‌های DEMO، `DRAFT_ONLY` و پرچم‌های عدم‌تأیید نمایش داده می‌شوند. شناسه بازبین، مرجع شواهد، محتوای پاسخ، پرونده دیگران و اطلاعات صادراتی پنهان هستند. مسیر قدیمی فهرست خانوار و جزئیات همچنان برقرار است. قرارداد: [scoped-records-contract.md](scoped-records-contract.md). آزمون‌ها: `backend/tests/test_household_progress_worklist.py` (۱۴ آزمون آفلاین).


## جزئیات پرونده خانوار و پیگیری وضعیت فنی — فقط LOCAL/TEST

قابلیت بعدی «پرونده‌های من» در همان محیط مشترک کاربران توسعه یافت: با دفتر بررسی فنی تزریق‌شده و نشست Keycloak معتبر، خانوار می‌تواند صفحه `/my-drafts/{ref}` را برای پرونده Domestic متعلق به خودش ببیند. مسیر JSON خواندنی `/api/v1/domestic/household-intake/my-drafts/{ref}/technical-status` فقط **وضعیت فنی مشاهده‌شده** و نسخه را نشان می‌دهد؛ متن شواهد، مرجع پاسخ، شناسه بازبین یا تأیید Business را افشا نمی‌کند. همه پرونده‌ها `DRAFT_ONLY` هستند و حتی `HUMAN_RESPONSE_RECORDED` تأیید طرح کشت نیست.

این نما فقط با نمونه مشترک `SqliteSyntheticHumanReviewLedger`، احراز هویت امضاشده و مجوز مالک دقیق پرونده فعال است؛ اجرای پیش‌فرض و دیتابیس SQLite معمولی بدون تاریخچه بررسی آن را فعال نمی‌کنند. دسترسی اشتباه `404`، خطای دفتر `503`، و نشست نامعتبر `401` می‌گیرد. **هیچ دکمه ثبت، ویرایش یا تأیید وجود ندارد.** قرارداد کامل: [scoped-records-contract.md](scoped-records-contract.md). آزمون: `backend/tests/test_owned_household_technical_status.py` (۱۳ سناریو).


## پرونده‌های من — محیط مشترک کاربران (فقط LOCAL/TEST)

در همان محیط کاربران و همکاران `/`، خانوار دارای نشست معتبر Keycloak می‌تواند فهرست تغییرناپذیر پرونده‌های **Domestic متعلق به شناسه امضاشده خودش** را ببیند. مسیر GET آزمایشی `/api/v1/domestic/household-intake/my-drafts` دارای صفحه‌بندی و ممیزی تراکنشی است؛ فقط با تزریق صریح `SqliteSyntheticGrantLedger` فعال می‌شود. کاربران دیگر، کارشناسان، خریداران و کارکنان داخلی از صرف نقششان به پرونده خانوار دسترسی ندارند. داده‌ها DEMO هستند؛ وضعیت تمام پرونده‌ها `DRAFT_ONLY` و وضعیت رضایت و تأیید متخصص منفی/تأییدنشده می‌ماند. هیچ ثبت، ویرایش، پذیرش، فروش یا پرداختی فعال نیست.

کد: `ronas_api/owner_case_api.py`، `ronas_api/grant_ledger_sqlite.py` و `ronas_api/ui_bff.py`. قرارداد کامل در [scoped-records-contract.md](scoped-records-contract.md) و ۱۵ آزمون در `backend/tests/test_owned_household_drafts.py` است. این قابلیت پایه‌ای برای توسعه آینده محیط مشترک است، نه مجوز استفاده از داده شخصی، اتصال واقعی Keycloak یا عبور از Gateهای Business.


## فهرست فنی بررسی شواهد برای اپراتور مجاز — فقط LOCAL/TEST

قابلیت کاربردی جدید در `human_review_sqlite.py`، `technical_review_api.py` و `ui_bff.py` پیاده شده است: فهرست صفحه‌بندی‌شده فقط از **پرونده‌های ساختگی تخصیص‌یافته با مجوز فعال**، همراه با نسخه پرونده، وضعیت فنی بررسی و وضعیت ثابت `DRAFT_ONLY`. یک تراکنش واحد بررسی مجوز و ممیزی نمایش هر ردیف را انجام می‌دهد؛ لغو مجوز، آن پرونده را از فهرست بعدی حذف می‌کند. Domestic و Export مستقل هستند؛ Finance و Governance از روی نقش خود به پرونده‌ها دسترسی پیدا نمی‌کنند.

این فهرست در دو مسیر GET آزمایشی `/api/v1/admin/domestic/household-intake/technical-review-worklist` و `/api/v1/admin/export/research/technical-review-worklist` و در **همان صفحه /admin موجود** قابل مشاهده است؛ مشروط به تزریق صریح یک نمونه مشترک از دفتر مجوز/بررسی و نشست مرورگر معتبر Keycloak. اجرای پیش‌فرض این مسیرها و رابط را فعال نمی‌کند. فهرست یک صف تصمیم‌گیری Business، مجوز بررسی کارشناسی، تأیید طرح کشت یا تعیین حقوق منبع صادرات نیست؛ هیچ endpoint تأیید یا پرونده واقعی ساخته نشده است.

قرارداد: [technical-human-review-contract.md](technical-human-review-contract.md). آزمون‌ها: `backend/tests/test_technical_review_worklist.py` شامل ۱۸ سناریوی API و صفحه مدیریت؛ CI باید برای HEAD همین PR سبز باشد.


## تاریخچه ثبت درخواست بررسی و پاسخ انسانی — فقط نمونه فنی

ماژول human_review_sqlite.py و قرارداد technical-human-review-contract.md گردش دو مرحله‌ای درخواست بررسی شواهد و ثبت مرجع پاسخ انسانی را با تأیید اختیار مستقل بازبین، کنترل نسخه، ثبت اتمیک و آزمون‌های امنیتی پیاده کرده‌اند. **وضعیت Business پرونده همواره DRAFT_ONLY باقی می‌ماند.** هیچ تأیید طرح کشت، حقوق منبع صادرات، داده واقعی یا API عمومی تصمیم انسانی در این مرحله فعال نشده است.


## دفتر آزمایشی پایدار لغو مجوز (2026-10-10)

[قرارداد SQLite و بازیابی](grant-ledger-sqlite-contract.md) و [کد ثبت تراکنشی](ronas_api/grant_ledger_sqlite.py) اضافه شد. رویداد ممیزی و لغو مجوز پرونده ساختگی به‌صورت اتمیک ذخیره می‌شوند و پس از بازگشایی SQLite اعتبارسنجی می‌گردند؛ هم‌زمانی، اجرای تکراری و خرابی تاریخچه رد می‌شوند. **این ابزار آزمون محلی تک‌میزبان است، نه پایگاه داده یا دفتر ممیزی Production**؛ در اجرای پیش‌فرض فعال نیست.


## تاریخچه نسخه و ممیزی لغو مجوز پرونده — نمونه فنی

[قرارداد audit و revocation](scoped-audit-contract.md) و ماژول [scoped_audit.py](ronas_api/scoped_audit.py) به نمونه‌های ساختگی اضافه شد. تاریخچه فقط نسخه‌های تغییرناپذیر *از قبل تعریف‌شده* را نشان می‌دهد؛ ممیزی خواندن و لغو دسترسی صرفاً در حافظه فرایند به صورت زنجیره هش نگهداری می‌شود، نه در لاگ مستقل یا دیتابیس Production. لغو فقط با callback اختیارات مستقلِ تزریق‌شده به کد (بدون endpoint عمومی) و کنترل نسخه انجام می‌شود؛ توکن معتبر Keycloak پس از لغو نیز مجوز پرونده را بازنمی‌گرداند. **این قرارداد هیچ مرجع واقعی اختیار و هیچ سیاست نگهداری داده یا مجوز بهره‌برداری تأییدشده‌ای نمی‌سازد.**


## محدوده دسترسی هر پرونده (نمونه، 2026-10-10)

[قرارداد پرونده‌های سطح رکورد](scoped-records-contract.md) و ماژول scoped_drafts.py اضافه شده‌اند. کارشناس Domestic یا Export حتی با نقش امضاشده Keycloak فقط پرونده ساختگی‌ای را می‌خواند که صریحاً به شناسه وی تخصیص داده شده باشد؛ خانوار تنها پرونده خود را می‌خواند. داده واقعی، تأیید و تراکنش نداریم؛ مسیرهای جدید در اجرای پیش‌فرض غیرفعال هستند.


## CURRENT: encrypted local session reference and role-gated two-shell BFF (2026-10-10)

These are tested implementation candidates, not a selected production datastore or live service. The explicit optional BFF serves exactly TWO server-authenticated HTML views: / for Ronas users/partners, /admin for one admin panel whose sections are filtered by signed Keycloak client roles. No customer PII, commercial activity, real login or hosting is activated.

backend/ronas_api/session_sqlite.py is a local/test reference: encrypted AES-256-GCM session and pending PKCE data at rest; SHA-256 lookup digests rather than bearer cookies in SQLite keys; transactional one-time pending-state consumption, multi-connection visibility, time-limited sessions, revocation, and fail-closed decryption. It is NOT the production or distributed session datastore. No default encryption key exists.

backend/ronas_api/ui_bff.py renders only server-authorized synthetic case cards in the two approved shells. Client-side logout script fetches same-origin CSRF and calls server-side revocation without ever holding an access token. The original prototype/ui pages remain independent offline static demonstrations. A missing authorized session cannot render protected cards.

Default app does NOT mount /, /admin, /api/auth/start, /api/auth/logout, or a session store. Only explicit create_app(config, browser_flow) in offline tests mounts these routes. REAL Keycloak and operational multi-replica session storage are not configured. See backend/oidc-browser-contract.md and infra/keycloak/README.md. Business #2/#3/#4 OPEN; PRs Draft/Open/Unmerged, no deployment.

Reproduction: PYTHONPATH=backend python -m unittest discover -s backend/tests -v. All signing and encryption test keys are ephemeral and synthetic.

---

## مصوبه Keycloak و مرز استقرار

کارفرما در 2026-10-10 **Keycloak خودمیزبان** را تصویب کرده است. اجرای پیش‌فرض اکنون فقط KeycloakConfig.from_environment را فعال می‌کند و امضاهای public JWKS و نقش‌های مختص API Client روناس، audience و azp را ارزیابی می‌کند. آداپتر عمومی قبلی AuthConfig صرفاً برای تزریق آزمون‌های ایزوله باقی مانده است و Runtime پیش‌فرض راه میانبر به هویت غیر-Keycloak ندارد. [راهنمای اتصال Keycloak](../infra/keycloak/README.md). هیچ سرور واقعی Keycloak، کاربر یا Client هنوز فراهم نشده است.


Status: **isolated, unadmitted Technical/API candidate** on draft PR #9, not Production or the selected Ronas technology stack. Backend implements real HTTP routing through FastAPI and real signature verification for trusted RS256 JWTs (PyJWT/cryptography). It intentionally exposes **read-only synthetic examples only**, no live household data, approved consent workflow, registration, payment, trading, external provider API or operational database. The old standalone UI demo is separate; opt-in authenticated BFF views are now independently tested.

## Historical generic OIDC adapter (test-only, superseded by approved Keycloak)

The RONAS_OIDC_* settings described in the following historical section are NOT accepted by the default runtime: only RONAS_KEYCLOAK_* provisioned by the trusted operator can configure its protected API.

## Authentication and scope
Requires four explicit runtime values: RONAS_OIDC_ISSUER (exact HTTPS issuer), RONAS_OIDC_AUDIENCE (actual API audience), RONAS_OIDC_KEY_ID (pinned external signer key ID), RONAS_OIDC_PUBLIC_KEY_FILE (absolute path to read-only RSA public-key PEM from that signer). **No values are supplied here, and no real provider has been configured or approved**. Missing/invalid config leaves all protected routes blocked with 503. Liveness GET /healthz does not indicate readiness; GET /readyz checks local public-key configuration only.

A signed Bearer token must have expected RS256 signature, key ID, issuer, audience, expiration, issued-at, not-before and subject plus an issuer-signed array named ronas_roles using the exact approved role vocabulary. Server-side authorization checks each route independently; a finance or governance role cannot access household/export data without its own separate explicit grant. Browser scripts, X-Role headers, unauthenticated JSON and synthetic sessionStorage are **never** role sources. No token minting, test/development login, automatic admin privileges or writable routes exist.

## Read-only endpoints
- GET /api/v1/me — verified subject and roles
- GET /api/v1/domestic/household-intake/example — household role only, always DEMO-H01, unverified consent
- GET /api/v1/admin/domestic/household-intake/example — domestic_ops only, same fake record
- GET /api/v1/admin/export/research/example — export_ops only, DEMO-SOURCE-01 rights unverified, no buyer/contract
- GET /api/v1/admin/finance/status — finance role only, never a transfer
- GET /api/v1/admin/governance/status — governance role only, never an authorization to approve operational records

The remaining external roles local_buyer, agronomy_expert, equipment_seller and export_supplier may read only GET /api/v1/me until explicit Business scope exists. Eliminated portals #6/#8/#9/#13 and API-only logistics #5 are not recreated. UI approval RON-DEC-030/031 is preserved; no cross-engine access inherited from a shared UI.

## Verification
From repo root, Python 3.12 virtualenv:
1. python -m pip install -r backend/requirements-test.txt
2. PYTHONPATH=backend python -m unittest discover -s backend/tests -v
3. PYTHONPATH=backend python -m compileall -q backend/ronas_api

Tests generate ephemeral RSA private keys in process and check signed access tokens, bad claims, tampered keys, role isolation, failure without issuer/key configuration, disabled write routes, and security headers. **Never commit an IdP private key or paste live credentials**.

## Next gates
Production OIDC issuer + controlled role mapping, key rotation/JWKS and revocation policy, live browser PKCE, operational distributed server sessions, global permission revocation, records/tenant-level ownership, consent and data retention, lawful source permissions, observability, Postgres/hosting/NFR/ADR, security testing and human review are **not complete**. A configured RSA public key is NOT evidence of legal data access or deployment readiness. Domestic Gate #2 / Export Gate #3 / Finance Gate #4 stay OPEN; PR #1 and #9 stay Draft/Open/Unmerged. No Stage/QA approval/Release/Production is implied.
