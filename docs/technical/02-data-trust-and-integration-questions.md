# Ronas — Data, Trust, Evidence and External Dependency Questions

**Status:** RISK/REQUIREMENT DISCOVERY / NOT AN ENACTED SECURITY POLICY OR INTEGRATION SPEC.  
**Source:** [Business quality](../business/19-business-quality-attributes-and-invariants.md)، [conceptual records](../business/26-conceptual-information-structure.md)، [external services](../business/27-shared-services-and-external-boundaries.md)، [operational evidence](../business/41-operations-evidence-and-escalation-map.md)، [Review 51](../business/51-integrated-business-review-findings.md).

## ۱. اطلاعات و نقاط اعتماد که باید در Technical بررسی شوند

| مرز داده و اعتماد | داده/شاهد مطرح در Business | سؤال امنیت/مالکیت برای طراحی بعدی | هنوز غیرمصوب |
| --- | --- | --- | --- |
| خانوار | هویت، آدرس/فضای کشت، تصویر و مشاهده | داده حداقلی، رضایت، انقضا، دسترسی عضو و بازبین چیست؟ | سیاست نگهداری/حذف، role و identity provider |
| شریک بازار داخلی | محصول/تجهیزات/تحویل/شکایت | سند فروش و مسئولیت طرف چگونه جدا می‌مانند؟ | فروشنده مجاز، زمان انتقال ریسک، PSP |
| تأمین حرفه‌ای Export | ظرفیت، محصول، قراردادهای مستقل | محرمانگی اسناد، scope طرف و اجازه اشتراک چیست؟ | KYC/اهلیت، شرایط قرارداد و ذخیره‌سازی |
| QC/فرآوری/محموله | استاندارد محصول–مقصد، آزمایش/لات | پیوند صحیح مدرک به کالا و مرجع علمی چیست؟ | معیار PASS، صدور گواهی و مالکیت |
| صادرات و مالی | اسناد فروش/ترخیص/تحویل و وصول/هزینه | تفکیک رسید از ادعا و انطباق هر قرارداد چگونه است؟ | بانک/ارز/حسابداری و اتصال واقعی |
| AI/محتوا/باشگاه | داده کشاورزی، تحلیل/یادگیری، RXP | آیا منبع داده برای آن استفاده **مجاز** است و خروجی فقط توصیه است؟ | Dataset، مدل، threshold، AI runtime |
| تغییر و اعتراض | شاهد ناقص، نسخه تصمیم و اعتراض | تصحیح داده چگونه با حق حذف و تعهد تاریخی سازگار می‌شود؟ | retention/evidence schema/workflow |

## ۲. گزینه‌های کنترلی برای مطالعه (PROPOSED, not security architecture)

- **Separation by scope:** روش احراز مجوز هر درخواست برای موتور و هر پرونده، بدون اعتماد به عنوان ظاهری نقش. شکل RBAC/ABAC/Policy engine هنوز انتخاب نشده.
- **Evidence provenance:** نسخه، منبع/اعتبار و ارتباط با تصمیم باید با صاحب Business بررسی شود؛ این بند دستور برای Append-only DB یا Event-sourcing نیست.
- **Consent and purpose:** استفاده داده برای آموزش AI یا مقایسه موتورها باید بر حق داده و هدف مصوب منطبق باشد؛ اصل «هر داده برای هر هدف قابل استفاده است» قابل‌قبول تلقی نمی‌شود.
- **Uncertain facts:** معلوم نبودن سلامت خوراکی، تأیید مقصد یا وصول نباید در طراحی از روی نمونه Figma، سند منبع یا دکمه فرضی به تأیید واقعی تبدیل شود؛ رفتار Fail Safe نیازمند تصمیم Business است.
- **Auditability:** حد مشاهده/ویرایش/تصمیم مالی و QC و گزارش مدیریتی باید از قرارداد کاربران استخراج شود؛ کنترل فنی بعداً انتخاب خواهد شد.

## ۳. ثبت وابستگی بیرونی با وضعیت واقعی

| طبقه ارائه‌دهنده احتمالی | داده/عملکرد ممکن | وضعیت فعلی |
| --- | --- | --- |
| بانک/PSP/تسویه | دریافت، استرداد، احراز هویت مالی | **UNSELECTED / NO CONTRACT / NO INTEGRATION** |
| اقلیم و منبع علمی | داده آب‌وهوا، راهنمای کشاورزی | **NO LICENSED SOURCE VERIFIED** |
| آزمایشگاه/QC/استاندارد | نتیجه آزمون و مجوزهای محصول–مقصد | **NO VERIFIED PROVIDER OR CRITERIA** |
| هاب/حمل محلی | سپردن، نگهداری، تحویل و رسید | **NO OPERATIONAL INTERFACE OR SLA** |
| فرآوری/بسته‌بندی/حمل خارجی | ورودی، بچ، سند صادرات و حمل | **NO VERIFIED PROCESSOR/EXPORTER/CONTRACT** |
| ارتباطات دیجیتال و محتوا | اعلان و آموزش/باشگاه | **NO CHANNEL/PROVIDER AUTHORIZED** |
| ابزار AI و مدل | پیشنهاد، تحلیل، آموزش و ارزیابی | **NO AI FAMILY/DATASET/RUNTIME APPROVED** |

هیچ URL، Secret، بانک، Vendor، مدل، Endpoint یا برون‌سپاری از منبع یا این جدول استخراج نمی‌شود.

## ۴. نیازهای کیفی برای تبدیل به سناریوی قابل آزمون *پس از پذیرش Business*

| وجه کیفیت | سؤالِ معتبر | عدد/رفتار نامعلوم |
| --- | --- | --- |
| دسترس‌پذیری و خدمت‌رسانی | کاربران Domestic و شرکای Export واقعاً چه ساعاتی/کانالی نیاز دارند؟ | SLA/SLO، پشتیبانی |
| مقیاس و بار | چند عضو هم‌زمان، ثبت مشاهده/تصویر، سرنخ صادرات یا پرونده QC وجود خواهد داشت؟ | Throughput, concurrency, size |
| حفاظت داده | الزامات قانونی در ایران و کشورهای مقصد، کاربران و اسناد چیست؟ | retention, residency, deletion, encryption profile |
| توان بازیابی | چه مدت اختلال یا از دست‌رفتن داده واقعاً قابل تحمل است؟ | RTO/RPO, restore frequency |
| صحت و ممیزی | کدام اسناد باید غیرقابل انکار، نسخه‌دار، قابل تصحیح و قابل اعتراض باشند؟ | audit retention, signature policy |
| هزینه/اپراتوری | بودجه/توان نگهداری و محدودیت زیرساخت روناس چیست؟ | hosting/cost/ops standards |
| تجربه دسترس‌پذیر | نقش خانوار/کارشناس/خریدار خارجی چه زبان و کانالی می‌خواهد؟ | localization, platform, accessibility acceptance |
| AI/علمی | خروجی پیشنهاد در چه Scope و با چه معیار علمی/خطا قابل دفاع است؟ | model size, training, inference, thresholds |

**این جدول NFR مصوب ندارد؛ معماری واقعی بدون صورت‌مسأله قابل سنجش و شواهد تصمیم گرفته نمی‌شود.**
