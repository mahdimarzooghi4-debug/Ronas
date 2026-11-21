const A = 'assets/';
const nav = [
  ['home', 'خانه', 'home.svg'], ['assistant', 'دستیار', 'assistant.svg'],
  ['training', 'آموزش', 'education.svg'], ['greenhouse', 'گلخانه', 'crop.svg'],
  ['market', 'بازار', 'market.svg'], ['equipment', 'تجهیزات', 'nav-equipment.svg'],
  ['account', 'حساب', 'account.svg'],
];
const pages = {
  assistant: ['دستیار روناس', 'راهنمای نمونه برای شروع؛ محتوای این بخش توصیه تخصصی یا تصمیم کشت نیست.', [
    ['از کجا شروع کنم؟', 'وضعیت گلخانه و فضای کشت نمونه را مرور کن.', '#greenhouse', 'مشاهده گلخانه'],
    ['برنامه امروز', 'بازدید از رطوبت خاک و ثبت مشاهده، نمونه‌های نمایشی هستند.', '#observation', 'ثبت مشاهده نمونه'],
    ['یادگیری آبیاری', 'درس کوتاه آبیاری ریحان را ببین.', '#lesson', 'رفتن به درس'],
  ]],
  training: ['آموزش کشت', 'دوره‌ها و درس‌های نمایشی روناس.', [
    ['آبیاری ریحان', 'درس نمونه · ۱۲ دقیقه · سطح مقدماتی', '#lesson', 'مشاهده درس'],
    ['آشنایی با گلخانه', 'راهنمای نمونهٔ آماده‌سازی گلخانه.', '#greenhouse', 'مشاهده راهنما'],
  ]],
  lesson: ['درس نمونه: آبیاری ریحان', 'محتوای آموزشی فرضی و غیرتخصصی برای نمایش مسیر اپ.', [
    ['مرور نکته‌ها', 'برای دیدن راهنمای شروع کشت به بخش دستیار برو.', '#assistant', 'راهنمای دستیار'],
    ['کارهای امروز', 'چک‌لیست فرضی روزانهٔ گلخانه.', '#greenhouse', 'رفتن به گلخانه'],
  ]],
  greenhouse: ['گلخانهٔ من', 'وضعیت نمونه؛ این اعداد از حسگر یا پروندهٔ واقعی نیامده‌اند.', [
    ['گلخانه بهار', 'وضعیت نمایشی: فعال · ۲ بستر کشت · بازدید: امروز', '#observation', 'ثبت مشاهده نمونه'],
    ['ریحان', 'مرحلهٔ رشد نمونه: برگ‌دهی · مساحت فرضی: ۲۴ مترمربع', '#harvest', 'برنامه برداشت نمونه'],
    ['گزارش‌های روزانه', 'گزارش‌های ساختگی برای نمایش روند ثبت.', '#observation', 'مشاهده گزارش‌ها'],
  ]],
  observation: ['ثبت مشاهدهٔ گلخانه', 'این فرم‌نما چیزی ثبت نمی‌کند؛ دکمه فقط پیام نمایشی را نشان می‌دهد.', [
    ['رطوبت خاک', 'مقدار نمونه: مناسب · بستر شمارهٔ ۱', '#observation-done', 'ثبت نمونه'],
    ['کارهای امروز', 'فهرست کارهای نمایشی گلخانه.', '#greenhouse', 'بازگشت به گلخانه'],
  ]],
  'observation-done': ['مشاهدهٔ نمونه', 'مشاهدهٔ فرضی ثبت شد؛ این فقط نمایش است و جایی ذخیره نشده.', [
    ['گلخانهٔ من', 'بازگشت به صفحهٔ وضعیت گلخانه.', '#greenhouse', 'مشاهده گلخانه'],
  ]],
  harvest: ['برداشت نمونه', 'اطلاعات فرضی‌اند و سفارش یا فروش واقعی ایجاد نمی‌کنند.', [
    ['ریحان تازه', 'مقدار نمونه: ۸ کیلوگرم · زمان پیشنهادی: این هفته', '#market', 'بازار نمونه'],
    ['راهنمای برداشت', 'نکته‌های آموزشی نمونه.', '#lesson', 'رفتن به آموزش'],
  ]],
  market: ['بازار محصولات', 'کاتالوگ فرضی؛ قیمت، موجودی و خرید واقعی فعال نیست.', [
    ['ریحان تازه', 'بستهٔ نمونهٔ ۵۰۰ گرمی · ۸۵٬۰۰۰ تومان', '#product', 'جزئیات محصول'],
    ['سبزی خوردن', 'بستهٔ نمونهٔ ۴۰۰ گرمی · ۷۰٬۰۰۰ تومان', '#product', 'جزئیات محصول'],
    ['سبد خرید', 'سبد نمایشی و بدون سفارش واقعی.', '#cart', 'مشاهده سبد'],
  ]],
  product: ['ریحان تازه', 'محصول نمونهٔ بازار روناس؛ قیمت و موجودی فرضی هستند.', [
    ['افزودن به سبد نمونه', 'این دکمه فقط صفحهٔ سبد نمایشی را باز می‌کند.', '#cart', 'رفتن به سبد'],
    ['ادامه خرید', 'فهرست محصولات نمونه.', '#market', 'بازگشت به بازار'],
  ]],
  cart: ['سبد خرید نمونه', 'سبد خالی است؛ سفارش و پرداخت واقعی انجام نمی‌شود.', [
    ['ادامه خرید', 'محصولات نمونهٔ بازار.', '#market', 'بازگشت به بازار'],
    ['سفارش‌های من', 'وضعیت سفارش فرضی.', '#orders', 'پیگیری سفارش‌ها'],
  ]],
  orders: ['سفارش‌های من', 'فقط وضعیت‌های ساختگی نمایش داده می‌شوند.', [
    ['سفارش نمونهٔ RN-2048', 'در حال آماده‌سازی · تاریخ نمایشی ۱۴۰۵/۰۸/۲۸', '#order', 'پیگیری سفارش'],
    ['بازار محصولات', 'فهرست محصولات نمونه.', '#market', 'رفتن به بازار'],
  ]],
  order: ['پیگیری سفارش نمونه', 'شناسه RN-2048 ساختگی است و به شرکت حمل‌ونقل وصل نیست.', [
    ['ثبت در سامانه', 'نمایشی · ۱۴۰۵/۰۸/۲۷', '#orders', 'بازگشت به سفارش‌ها'],
    ['آماده‌سازی', 'نمایشی · در انتظار تحویل', '#orders', 'بازگشت'],
  ]],
  equipment: ['تجهیزات کشاورزی', 'فهرست نمونه؛ درخواست خرید واقعی فعال نیست.', [
    ['آبیاری قطره‌ای', 'بستهٔ فرضی برای گلخانهٔ کوچک.', '#equipment-detail', 'مشاهده جزئیات'],
    ['گلدان کشت', 'مدل فرضی برای فضای محدود.', '#equipment-detail', 'مشاهده جزئیات'],
  ]],
  'equipment-detail': ['آبیاری قطره‌ای', 'مشخصات و قیمت این تجهیز فرضی هستند.', [
    ['درخواست نمونه', 'ادامه فقط مسیر نمایشی درخواست را باز می‌کند.', '#equipment-request', 'ادامه درخواست'],
    ['فهرست تجهیزات', 'برگشت به تجهیزات نمونه.', '#equipment', 'بازگشت'],
  ]],
  'equipment-request': ['درخواست تجهیزات نمونه', 'درخواست ذخیره نمی‌شود و برای فروشنده ارسال نمی‌شود.', [
    ['وضعیت درخواست', 'پیش‌نویس نمایشی · بدون ارسال.', '#equipment', 'بازگشت به تجهیزات'],
  ]],
  account: ['حساب کاربری', 'حساب نمونه؛ اطلاعات هویتی واقعی در این صفحه ذخیره نشده‌اند.', [
    ['اعلان‌ها', 'پیام‌های نمونهٔ اپلیکیشن.', '#notifications', 'مشاهده اعلان‌ها'],
    ['حریم خصوصی', 'تنظیمات نمایشی حساب.', '#privacy', 'تنظیمات حساب'],
    ['باشگاه روناس', 'محتوای نمونهٔ یادگیری.', '#club', 'ورود به باشگاه'],
  ]],
  notifications: ['اعلان‌ها', 'پیام‌های ساختگی؛ رویداد واقعی رخ نداده است.', [
    ['یادآوری بازدید گلخانه', 'امروز · یادآوری نمایشی.', '#greenhouse', 'مشاهده گلخانه'],
    ['درس تازه', 'آبیاری ریحان · محتوای آموزشی نمونه.', '#lesson', 'مشاهده درس'],
  ]],
  privacy: ['تنظیمات و حریم خصوصی', 'این صفحه نمایشی است و تنظیمی تغییر نمی‌کند.', [
    ['داده‌های نمونه', 'داده‌های این نسخه به حساب واقعی متصل نیستند.', '#home', 'بازگشت به خانه'],
  ]],
  club: ['باشگاه روناس', 'محتوای نمونه برای یادگیری و آشنایی با کشاورزی.', [
    ['درس آبیاری ریحان', 'آموزش نمونهٔ کوتاه.', '#lesson', 'مشاهده درس'],
    ['گلخانهٔ من', 'بازگشت به فضای کشت نمونه.', '#greenhouse', 'مشاهده گلخانه'],
  ]],
};

const card = ([title, description, href, action]) =>
  `<article class="rn-screen-card"><h2>${title}</h2><p>${description}</p><a href="${href}">${action} ←</a></article>`;
const activeTab = (screen) => ({
  lesson: 'training', observation: 'greenhouse', 'observation-done': 'greenhouse', harvest: 'greenhouse',
  product: 'market', cart: 'market', orders: 'market', order: 'market',
  'equipment-detail': 'equipment', 'equipment-request': 'equipment', notifications: 'account', privacy: 'account', club: 'training',
}[screen] || screen);

function home() {
  return `<section class="rn-welcome"><h1>خانه‌ای سبزتر، هر روز نزدیک‌تر</h1><p>وضعیت گلخانه و مسیر بعدی تولیدت را یکجا ببین.</p></section>
    <a class="rn-hero" href="#greenhouse" aria-label="مدیریت گلخانه">
      <img class="rn-hero-image" src="${A}greenhouse-hero.png" alt="گلخانه‌ای سرسبز"><span class="rn-hero-shade"></span>
      <span class="rn-hero-status"><img src="${A}status-dot.svg" alt="">گلخانهٔ نمونه</span>
      <span class="rn-hero-copy"><small>تولید خانگی، با همراهی روناس</small><strong>گلخانهٔ من، در مسیر رشد</strong><span>مدیریت کشت، تجهیزات و محصولات</span><b>مدیریت گلخانه</b></span>
    </a>
    <section class="rn-summary"><div class="rn-section-title"><h2>خلاصه وضعیت</h2><span class="rn-connected">دادهٔ نمونه</span></div>
      <div class="rn-metrics"><article><small>گلخانه‌های من</small><strong>۱</strong><span>گلخانهٔ نمونه</span></article><article><small>وضعیت کشت</small><strong>فعال</strong><span>فرضی</span></article><article><small>کارهای امروز</small><strong>۳</strong><span>چک‌لیست نمونه</span></article></div></section>
    <a class="rn-assistant rn-assistant-link" href="#assistant"><span class="rn-assistant-icon"><img src="${A}sparkles.svg" alt=""></span><h2>دستیار هوشمند روناس</h2><p>راهنمای نمونه برای شروع کشت و کارهای گلخانه</p><span class="rn-disabled-label">مشاهده راهنمای نمونه ←</span></a>
    <section class="rn-services"><h2>خدمات روناس</h2><div class="rn-services-grid"><a class="rn-service" href="#equipment"><span class="rn-service-icon"><img src="${A}equipment.svg" alt=""></span><strong>تجهیزات کشاورزی</strong><small>مشاهده و انتخاب نمونه</small></a><a class="rn-service" href="#market"><span class="rn-service-icon"><img src="${A}basket.svg" alt=""></span><strong>بازار محصولات</strong><small>محصولات نمونه روناس</small></a><a class="rn-service" href="#club"><span class="rn-service-icon"><img src="${A}wallet.svg" alt=""></span><strong>باشگاه روناس</strong><small>آموزش و همراهی</small></a></div></section>
    <section class="rn-quick"><h2>دسترسی سریع</h2><div><a class="rn-primary-action" href="#greenhouse">کارهای امروز</a><a class="rn-secondary-action" href="#observation">ثبت مشاهده جدید</a></div></section>
    <section class="rn-cases"><h2>نمونه وضعیت گلخانه</h2><p>این اطلاعات فرضی‌اند و به API یا حسگر واقعی وصل نیستند.</p><ul><li><a href="#greenhouse">گلخانه بهار · فعال</a></li><li><a href="#observation">رطوبت خاک · نیازمند بازدید نمونه</a></li></ul></section>`;
}

function render() {
  const main = document.getElementById('main');
  const screen = location.hash.replace(/^#\/?/, '') || 'home';
  if (screen === 'home') {
    main.innerHTML = `${home()}${navigation('home')}`;
    document.title = 'روناس | خانه خانوار';
    return;
  }
  const data = pages[screen];
  if (!data) {
    main.innerHTML = `<section class="rn-screen"><h1>این صفحه پیدا نشد</h1><a class="rn-screen-back" href="#home">بازگشت به خانه</a></section>${navigation('home')}`;
    return;
  }
  const [title, intro, cards] = data;
  main.innerHTML = `<section class="rn-screen"><a class="rn-screen-back" href="#home">← بازگشت به خانه</a><h1>${title}</h1><p>${intro}</p><div class="rn-screen-grid">${cards.map(card).join('')}</div></section>${navigation(activeTab(screen))}`;
  document.title = `روناس | ${title}`;
  main.focus({ preventScroll: true });
}

function navigation(active) {
  return `<nav class="rn-bottom-nav" aria-label="ناوبری روناس">${nav.map(([key, label, icon]) =>
    `<a class="rn-nav-item${key === active ? ' rn-nav-active' : ''}" href="#${key}"${key === active ? ' aria-current="page"' : ''}><img src="${A}${icon}" alt=""><span>${label}</span></a>`
  ).join('')}</nav>`;
}

window.addEventListener('hashchange', render);
render();
