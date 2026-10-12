# روناس — ساختار مفهومی سیاست، تغییر و نسخه تصمیم | Structural Draft v0.14

**Status:** DERIVED CHANGE-GOVERNANCE QUESTIONS — not an enacted policy registry, effective-date algorithm, status machine, review SLA or migration plan.  
**Approved:** RON-DEC-007 مراحل تولید محصول را الزامی می‌کند؛ RON-DEC-008 بازبینی نهایی را تا پایان تهیه ساختار موکول می‌کند.  
**Basis:** [ثبت تصمیم‌ها](04-decisions-and-open-questions.md)، [پذیرش Business](20-business-baseline-and-technical-admission-gates.md)، [قراردادهای صادرات مستقل](11-export-multicontract-direction.md)، [مشاهده/شواهد](41-operations-evidence-and-escalation-map.md)، [گزارش مدیریتی](36-management-reporting-and-metric-candidates.md).

## ۱. چه چیزهایی ممکن است در آینده تغییر کنند؟ (CANDIDATE CHANGE DOMAINS)

| دامنه تغییر | مثال مشخص در ساختار | تأثیر محتمل که باید بازبینی شود | مرجع تصمیم واقعی |
| --- | --- | --- | --- |
| حدود خدمت Domestic | آموزش عمومی در برابر ثبت کشت یا بازار | حقوق کاربر، شرایط عضویت، داده، قیمت/ایمنی | OPEN |
| استاندارد/دانش کشاورزی | نسخه محتوا/روش بررسی سلامت خوراکی | اعتبار توصیه قدیمی، خطا یا اعتراض | OPEN |
| شریک تجهیزات/هاب/حمل | شرایط همکاری، مجوز، تضمین و نگهداری | تعهدات سفارش باز و موارد تحویل‌نشده | OPEN |
| محصول–مقصد Export | استاندارد، خریدار یا الزامات جدید مقصد | مرز QC/مجوز و محموله‌های قبلی/جاری | OPEN |
| توافق تجاری Export | تغییر شروط هر رابطه مستقل P/A/S/J یا نوع دیگر | مالکیت، قیمت، تعهد، هزینه، اثر بر قراردادهای مرتبط | OPEN |
| روش مالی/گزارش | تعریف درآمد، هزینه، وجه/سود، کارمزد و اصلاح | دوره گزارش/محاسبه/عدم دوباره‌شماری | OPEN |
| سیاست داده | رضایت، هدف استفاده، محدودیت دسترسی/حذف | داده‌های قبلی، مدل‌های AI و حق اشتراک | OPEN |
| پیشنهادهای AI و آموزش | منبع داده یا مدل/الگو یا محتوای آموزشی | دقت/حقوق داده، مسئول نتیجه و شواهد یادگیری | OPEN |
| تعریف گیت و پذیرش محصول | دامنه Business، معیار پذیرش یا وابستگی | قابل‌اتکا بودن ADR/Backlog/Sprint بعدی | PROCESS APPROVED; CONTENT OPEN |

**کد وضعیت پیشنهادی یا فرض نرخ/مدت اعتبار از این جدول استخراج نمی‌شود.**

## ۲. اطلاعات مفهومی برای درخواست تغییر (نه schema یا دستور ثبت)

```text
Proposed change and business reason:
Engine: Domestic / Export / cross-cutting (explicitly scoped)
What source text / decision / contract is being challenged:
Previous meaning and version (if a real approved version exists):
Proposed revised meaning and its explicit exclusions:
Potentially affected actors, data, goods, cash, partner agreements:
New evidence and contradictory/missing evidence:
Legal, QC, finance and privacy dependencies:
Historical cases / open obligations potentially affected:
Who could review, and proof of actual authority (UNASSIGNED):
Requested disposition: PROPOSED | OPEN | DEFERRED | REJECTED | APPROVED*
* APPROVED only from an authorized real decision, not by creating this template.
```

## ۳. چهار خطای تغییر که باید پیش از اجرای سیستم بررسی شوند

| خطر | مسئله قابل ارزیابی | آنچه در حال حاضر **معلوم نیست** |
| --- | --- | --- |
| **بازنویسی تاریخچه** | تغییر دستورالعمل کیفیت روی بررسی پیشین چه اثری دارد؟ | تاریخ مؤثر، نسخه مرجع و قواعد بررسی مجدد |
| **اختلاط مستقل‌ها** | تغییر مدل کارمزد/قرارداد Export به Domestic یا قرارداد دیگر تسری داده شود | حدود مجاز تسری و گیت/اجازه مستقل |
| **تصحیح در برابر حذف** | کاربر/متخصص شاهد اشتباه را اصلاح می‌کند؛ چه چیز باید قابل ردگیری بماند؟ | منشأ، حق اصلاح/حذف، سیاست نگهداری |
| **تغییر در زمان تعهد باز** | قرارداد/شرایط هاب یا QC تغییر می‌کند؛ سفارش/محموله/طلب پیشین چه می‌شود؟ | مرجع معتبر اسناد و تعهدات تاریخی |

این نکات **الزامات طراحی مورد مطالعه‌اند**، نه حکم قطعی «همیشه نسخه قدیمی» یا «بازمحاسبه همه‌چیز».

## ۴. مدل مفهومی تغییر — مبنای بررسی، نه جریان سیستمی

```text
[درخواست تغییر قابل انتساب]
       ⋮ مسئله/منبع/دامنه/اثر
[جمع‌آوری شواهد و آراء ذی‌نفعان]
       ⋮ صلاحیت مرجع هنوز OPEN
[تصمیم واقعی صاحب اختیار برای Scope مشخص]
       ⋮ نسخه/تاریخ اثر فقط پس از قرارداد مصوب
[تعیین اثر بر پرونده‌های قبلی و جاری]
       ⋮ بررسی حقوق داده، قرارداد، کیفیت و مالی
[در صورت عبور گیت‌ها: طراحی/بازطراحی Technical]
```

**این شکل یک دستور انتقال خودکار، Version Registry اجرایی، trigger برای Production، API اداری یا برنامه مهاجرت داده نیست.**

## ۵. جداسازی تغییر Business از تغییر نرم‌افزار

1. **تغییر Business/contract:** نیازمند منبع، واقعیت معتبر، صاحب اختیار، دامنه، اثر قراردادها و پذیرش جدید/اصلاح‌شده.
2. **تغییر Technical/Software (بعداً):** تنها روی قرارداد پذیرفته‌شده، مطابق Technical/ADR/Backlog/Sprint و گیت‌های Code/Release.
3. **تغییر مشاهده یا داده:** به معنای تصمیم درباره کیفیت، قرارداد یا مبلغ نیست؛ منبع، مجوز و منطق تصحیح جدا بررسی شوند.
4. **تغییر AI/model (بعداً):** داده/ارزیابی/حاکمیت و مجوز Production هنوز تعیین نشده‌اند؛ صرف کیفیت بهتر، ارتقای خودکار نمی‌سازد.

## ۶. خروجی قابل ارائه به مرور نهایی آینده

پرونده پیشنهادی برای هر خط‌مشی یا قرارداد باید «نسخه، اثر زمانی، دامنه مستقل، مرجع، شواهد، تغییر و استثناهای تاریخی» را **به‌عنوان سؤال قابل تصمیم** داشته باشد. تا تصویب Business، هیچ سیاست مالی/خوراکی/صادراتی یا الگوریتم تعیین نسخه در محصول وجود ندارد.
