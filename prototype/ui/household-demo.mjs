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

const primaryTabs = [
  ['home', 'خانه', 355], ['assistant', 'دستیار', 299], ['training', 'آموزش', 243],
  ['greenhouse', 'کشت', 187], ['market', 'بازار', 131], ['equipment', 'تجهیزات', 75],
  ['account', 'حساب', 19],
];
const frameScenes = {
  home: { node: '154-85', height: 1302, title: 'خانه خانوار', links: [
    [24, 190, 382, 300, 'greenhouse', 'مدیریت گلخانه'],
    [24, 666, 382, 140, 'assistant', 'دستیار هوشمند روناس'],
    [221, 870, 185, 116, 'market', 'بازار محصولات'],
    [24, 870, 185, 116, 'equipment', 'تجهیزات کشت'],
    [24, 998, 382, 84, 'training', 'باشگاه روناس و آموزش'],
    [221, 1140, 185, 52, 'observation', 'ثبت مشاهده جدید'],
    [24, 1140, 185, 52, 'greenhouse', 'کارهای امروز'],
  ]},
  greenhouse: { node: '199-426', height: 1862, title: 'مدیریت گلخانه و برنامه کشت', links: [
    [24, 192, 382, 240, 'harvest', 'گلخانه و کشت فعال'],
    [24, 628, 120, 164, 'harvest', 'ریحان'], [155, 628, 120, 164, 'harvest', 'کاهو'],
    [286, 628, 120, 164, 'harvest', 'نعناع'],
    [24, 856, 382, 176, 'training', 'برنامه کشت نمونه'],
    [24, 1096, 382, 304, 'report-preview', 'کارهای روز و گزارش‌ها'],
    [24, 1668, 382, 52, 'observation', 'ثبت گزارش روزانه گلخانه'],
  ]},
  market: { node: '218-550', height: 1194, title: 'بازار روناس', links: [
    [24, 112, 130, 36, 'orders', 'سفارش‌های خرید'],
    [24, 482, 382, 136, 'product', 'جزئیات محصول نمونه'],
    [24, 630, 382, 136, 'product', 'جزئیات محصول نمونه'],
    [24, 778, 382, 104, 'order-tracking', 'روش‌های تحویل نمونه'],
    [24, 894, 382, 90, 'market', 'مسیر فروش نمونه'],
    [24, 996, 382, 50, 'orders', 'مشاهده فروش و سفارش‌ها'],
  ]},
  equipment: { node: '176-478', height: 1728, title: 'تجهیزات پیشنهادی', links: [
    [24, 190, 382, 276, 'equipment-detail', 'شروع بررسی تجهیزات'],
    [24, 710, 382, 252, 'equipment-detail', 'گلخانه خانگی کوچک'],
    [24, 974, 382, 252, 'equipment-detail', 'کیت آبیاری قطره‌ای'],
    [24, 1238, 382, 252, 'equipment-detail', 'سینی نشا و کشت'],
  ]},
  assistant: { node: '471-1653', height: 1321, title: 'دستیار هوشمند روناس', links: [
    [286, 453, 120, 118, 'greenhouse', 'کشت من'],
    [155, 453, 120, 118, 'report-preview', 'گزارش روزانه'],
    [24, 453, 120, 118, 'assistant', 'ارزیابی نمونه'],
    [24, 714, 382, 217, 'assistant', 'پاسخ نمونه دستیار روناس'],
    [24, 943, 382, 101, 'observation', 'کار بعدی: بررسی رطوبت بستر کشت'],
    [24, 1056, 382, 49, 'observation', 'بازکردن فرم مشاهده'],
    [24, 1117, 382, 62, 'assistant', 'پرسش نمونه'],
  ]},
  training: { node: '481-1684', height: 1210, title: 'آموزش کشت', links: [
    [24, 185, 382, 220, 'lesson', 'مسیر یادگیری کشت'],
    [24, 631, 382, 125, 'lesson', 'درس آبیاری ریحان'],
    [24, 768, 382, 125, 'report-preview', 'درس بررسی برگ‌ها'],
    [24, 957, 382, 111, 'observation', 'تمرین در گلخانه'],
  ]},
  account: { node: '510-1746', height: 1872, title: 'حساب خانواده', links: [
    [24, 185, 382, 161, 'account', 'حساب نمونه خانواده'],
    [24, 577, 382, 168, 'greenhouse', 'فضای کشت من'],
    [286, 809, 120, 117, 'greenhouse', 'کشت من'],
    [155, 809, 120, 117, 'training', 'آموزش'],
    [24, 809, 120, 117, 'report-preview', 'گزارش'],
    [24, 990, 382, 130, 'harvest', 'برداشت‌های نمونه'],
    [24, 1501, 382, 151, 'orders', 'سوابق فعالیت خانواده'],
    [24, 1664, 382, 66, 'account', 'تنظیمات و حریم خصوصی'],
  ]},
  notifications: { node: '865-1839', height: 1190, title: 'اعلان‌های خانواده', links: [
    [24, 376, 382, 139, 'greenhouse', 'کار گلخانه'],
    [24, 527, 382, 139, 'report-preview', 'گزارش نمونه ریحان'],
    [24, 678, 382, 139, 'lesson', 'درس آبیاری ریحان'],
    [24, 933, 382, 48, 'home', 'بازگشت به خانه'],
  ]},
  observation: { node: '207-488', height: 1440, title: 'فرم گزارش روزانه گلخانه', links: [
    [24, 338, 120, 72, 'observation', 'ریحان'], [155, 338, 120, 72, 'observation', 'کاهو'],
    [286, 338, 120, 72, 'observation', 'نعناع'], [24, 480, 382, 112, 'observation', 'عکس نمونه'],
    [24, 968, 382, 80, 'observation', 'وضعیت سلامت گیاه'],
    [24, 1060, 382, 80, 'observation', 'مشاهده آفت'],
    [24, 1244, 382, 52, 'report-preview', 'ذخیره گزارش نمونه'],
  ]},
  'report-preview': { node: '204-457', height: 1580, title: 'گزارش روزانه گلخانه', links: [
    [24, 332, 382, 188, 'report-preview', 'تصویر گزارش نمونه'],
    [24, 760, 382, 146, 'report-preview', 'مشاهده‌های روزانه نمونه'],
    [24, 1386, 382, 52, 'greenhouse', 'بازگشت به گلخانه'],
  ]},
  harvest: { node: '679-1808', height: 1387, title: 'برداشت محصول', links: [
    [24, 358, 122, 70, 'harvest', 'ریحان'], [154, 358, 122, 70, 'harvest', 'کاهو'],
    [284, 358, 122, 70, 'harvest', 'نعناع'], [24, 1180, 382, 40, 'market', 'مشاهده محصولات فروشندگان'],
  ]},
  lesson: { node: '505-1715', height: 1430, title: 'درس آبیاری ریحان', links: [
    [24, 214, 382, 236, 'lesson', 'تصویر درس'],
    [24, 514, 382, 118, 'lesson', 'مرحله اول درس'],
    [24, 644, 382, 118, 'lesson', 'مرحله دوم درس'],
    [24, 774, 382, 330, 'lesson', 'مرحله سوم درس'],
    [24, 1116, 382, 111, 'greenhouse', 'تمرین در گلخانه'],
    [24, 1239, 382, 49, 'observation', 'بازکردن فرم مشاهده'],
  ]},
  orders: { node: '333-1064', height: 1391, title: 'سفارش‌های خرید', links: [
    [24, 204, 382, 75, 'market', 'خرید محصولات و فروش'],
    [24, 481, 382, 251, 'order-tracking', 'سفارش در حال پیگیری'],
    [24, 796, 382, 233, 'order-tracking', 'سفارش تحویل‌شده نمونه'],
    [24, 1189, 382, 48, 'market', 'بازگشت به بازار'],
  ]},
  product: { node: '224-581', height: 1210, title: 'جزئیات محصول', links: [
    [24, 112, 382, 22, 'market', 'بازگشت به بازار'],
    [24, 150, 382, 240, 'product', 'تصویر محصول نمونه'],
    [24, 954, 382, 112, 'purchase-request', 'شرایط خرید نمونه'],
  ]},
  'purchase-request': { node: '229-612', height: 1236, title: 'درخواست خرید و تحویل', links: [
    [24, 106, 382, 22, 'product', 'بازگشت به محصول'],
    [24, 712, 382, 216, 'purchase-request', 'گزینه‌های تحویل نمونه'],
    [24, 1042, 382, 50, 'order-tracking', 'ثبت درخواست نمونه'],
  ]},
  'order-tracking': { node: '233-657', height: 1328, title: 'پیگیری سفارش', links: [
    [24, 112, 382, 22, 'orders', 'بازگشت به سفارش‌ها'],
    [24, 476, 382, 358, 'order-tracking', 'مراحل پیگیری نمونه'],
    [24, 1134, 382, 50, 'orders', 'جزئیات تحویل نمونه'],
  ]},
  'equipment-detail': { node: '177-333', height: 1442, title: 'جزئیات تجهیز', links: [
    [24, 190, 382, 260, 'equipment-detail', 'تصویر تجهیز'],
    [24, 1216, 382, 52, 'equipment-request', 'درخواست خرید تجهیز'],
    [24, 1280, 382, 52, 'equipment', 'بازگشت به تجهیزات'],
  ]},
  'equipment-request': { node: '194-364', height: 1526, title: 'درخواست خرید تجهیزات', links: [
    [24, 190, 382, 224, 'equipment-request', 'جزئیات تجهیز نمونه'],
    [24, 1362, 382, 54, 'equipment-tracking', 'ثبت درخواست نمونه'],
  ]},
  'equipment-tracking': { node: '196-395', height: 1548, title: 'پیگیری درخواست تجهیزات', links: [
    [24, 302, 382, 172, 'equipment-tracking', 'وضعیت درخواست تجهیز نمونه'],
    [24, 1286, 382, 52, 'equipment-detail', 'مشاهده جزئیات تجهیز'],
  ]},
};
const frameAliases = { club: 'training', privacy: 'account', 'order-detail': 'order-tracking' };

function navFrameLinks(height) {
  return [
    [355, height - 79, 56, 66, 'home', 'خانه'],
    [299, height - 79, 56, 66, 'assistant', 'دستیار'],
    [243, height - 79, 56, 66, 'training', 'آموزش'],
    [187, height - 79, 56, 66, 'greenhouse', 'کشت'],
    [131, height - 79, 56, 66, 'market', 'بازار'],
    [75, height - 79, 56, 66, 'equipment', 'تجهیزات'],
    [19, height - 79, 56, 66, 'account', 'حساب'],
    [24, 29, 46, 46, 'notifications', 'اعلان‌ها'],
  ];
}
function renderFigmaFrame(screen) {
  const scene = frameScenes[screen];
  if (!scene) return null;
  const links = [...navFrameLinks(scene.height), ...scene.links];
  const hotspots = links.map(([x, y, w, h, target, label]) =>
    `<a class="rn-frame-hit" href="#${target}" aria-label="${label}"><title>${label}</title><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="transparent"/></a>`
  ).join('');
  return `<section class="rn-frame-view" aria-label="${scene.title}"><div class="rn-frame-canvas">
    <img src="${A}figma-frames/${scene.node}.png" alt="صفحهٔ ${scene.title} مطابق فریم فیگما" width="430" height="${scene.height}">
    <svg class="rn-frame-links" viewBox="0 0 430 ${scene.height}" preserveAspectRatio="none" role="navigation" aria-label="دکمه‌ها و مسیرهای صفحه">${hotspots}</svg>
  </div></section>`;
}

function home() {
  return `<div class="rn-home-exact"><section class="rn-home-welcome"><h1>خانه‌ای سبزتر، هر روز نزدیک‌تر</h1><p>وضعیت گلخانه و مسیر بعدی تولیدت را یک‌جا ببین.</p></section>
    <a class="rn-hero" href="#greenhouse" aria-label="مدیریت گلخانه">
      <img class="rn-hero-image" src="${A}greenhouse-hero.png" alt="گلخانه‌ای سرسبز"><span class="rn-hero-shade"></span>
      <span class="rn-hero-status"><img src="${A}status-dot.svg" alt="">گلخانه فعال</span>
      <span class="rn-hero-copy"><small>تولید خانگی، با همراهی روناس</small><strong>گلخانه من، در مسیر رشد</strong><span>مدیریت کشت، تجهیزات و محصولات در یک تجربه یکپارچه</span><b>مدیریت گلخانه</b></span>
    </a>
    <section class="rn-summary"><div class="rn-section-title"><h2>خلاصه وضعیت</h2><span class="rn-connected">داده نمایشی</span></div>
      <div class="rn-metrics"><article><small>فضای کشت</small><strong>۱ فعال</strong><span>گلخانه</span></article><article><small>محصول جاری</small><strong>ریحان</strong><span>نمونه</span></article><article><small>مرحله رشد</small><strong>۳</strong><span>برگ‌دهی</span></article></div></section>
    <a class="rn-assistant rn-assistant-link" href="#assistant"><span class="rn-assistant-icon"><img src="${A}sparkles.svg" alt=""></span><h2>دستیار هوشمند روناس</h2><p>راهنمای نمونه برای به‌کارگیری کشت</p><span class="rn-disabled-label">مشاهده راهنمای نمونه</span></a>
    <section class="rn-services"><h2>خدمات روناس</h2><div class="rn-services-grid"><a class="rn-service" href="#market"><span class="rn-service-icon"><img src="${A}basket.svg" alt=""></span><strong>بازار محصولات</strong><small>عرضه و خرید خانگی</small></a><a class="rn-service" href="#equipment"><span class="rn-service-icon"><img src="${A}equipment.svg" alt=""></span><strong>تجهیزات کشت</strong><small>انتخاب و سفارش</small></a><a class="rn-service rn-club-service" href="#club"><span class="rn-service-icon"><img src="${A}wallet.svg" alt=""></span><strong>باشگاه روناس • پیش‌نمایش</strong><small>برنامه‌های مشارکتی، منابع آموزشی • هنوز فعال نیست</small></a></div></section>
    <section class="rn-quick"><h2>دسترسی سریع</h2><div><a class="rn-primary-action" href="#observation">ثبت مشاهده جدید</a><a class="rn-secondary-action" href="#orders">کارهای امروز</a></div></section>${navigation('home')}</div>`;
}

function render() {
  const main = document.getElementById('main');
  const screen = frameAliases[location.hash.replace(/^#\/?/, '')] || location.hash.replace(/^#\/?/, '') || 'home';
  document.body.classList.toggle('rn-show-logout', screen === 'account');
  const figma = renderFigmaFrame(screen);
  if (figma) {
    main.innerHTML = figma;
    document.title = `روناس | ${frameScenes[screen].title}`;
    main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    return;
  }
  if (screen === 'home') {
    main.innerHTML = home();
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
