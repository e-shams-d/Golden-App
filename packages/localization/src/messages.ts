export const faMessages = {
  "login.failure": "اطلاعات ورود معتبر نیست.",
  "login.password": "گذرواژه",
  "login.submit": "ورود",
  "login.submitting": "در حال ورود…",
  "trader.login.title": "ورود طلافروش",
  "trader.login.identifier": "شماره موبایل",
  "trader.login.identifierHint": "مثل ۰۹۱۲۳۴۵۶۷۸۹ — با ارقام فارسی یا انگلیسی",
  "trader.login.registerPrompt": "حساب ندارید؟ درخواست همکاری ثبت کنید.",
  "admin.login.title": "ورود کارکنان",
  "admin.login.identifier": "نام کاربری",
  "admin.login.identifierHint": "نام کاربری سازمانی شما",
  "common.skipToContent": "رفتن به محتوای اصلی",
  "common.retry": "تلاش دوباره",
  "common.refresh": "دریافت آخرین اطلاعات",
  "common.backToHome": "بازگشت به صفحه اصلی",
  "state.loading.title": "در حال دریافت اطلاعات",
  "state.loading.description": "لطفاً چند لحظه منتظر بمانید.",
  "state.error.title": "دریافت اطلاعات انجام نشد",
  "state.error.description": "ارتباط با سامانه برقرار نشد. دوباره تلاش کنید.",
  "state.empty.title": "هنوز موردی وجود ندارد",
  "state.empty.description": "با ثبت نخستین مورد، اطلاعات این بخش نمایش داده می‌شود.",
  "state.forbidden.title": "دسترسی مجاز نیست",
  "state.forbidden.description": "برای مشاهده این بخش دسترسی لازم را ندارید.",
  "state.conflict.title": "اطلاعات این صفحه تغییر کرده است",
  "state.conflict.description": "آخرین نسخه را دریافت و پیش از ادامه دوباره بررسی کنید.",
  // The three kinds slice 10C added. Each of the three had no component, no kind and no
  // wording, so a route answering 428, 409-idempotency or a lost connection had nothing to
  // render — a screen would have shown the generic error and said something untrue.
  "state.precondition.title": "پیش‌نیاز این درخواست کامل نیست",
  "state.precondition.description": "برای انجام این کار ابتدا باید مرحله‌ای دیگر انجام شود. صفحه را تازه کنید و دوباره تلاش کنید.",
  "state.idempotency.title": "این درخواست قبلاً ثبت شده است",
  "state.idempotency.description": "همین درخواست پیش‌تر با اطلاعات دیگری ارسال شده بود. برای جلوگیری از ثبت دوباره، انجام نشد.",
  // The wording is the control, not the styling. Somebody told an operation "failed" will
  // retry it; this state exists exactly where a retry could apply the same change twice,
  // so it says the result is unknown and asks them to check before acting.
  "state.timeout.title": "نتیجه این درخواست مشخص نیست",
  "state.timeout.description": "پاسخ سامانه دریافت نشد و معلوم نیست درخواست انجام شده یا نه. پیش از تلاش دوباره، وضعیت را بررسی کنید.",
  "trader.appName": "سامانه طلا ـ پنل طلافروش",
  "trader.shellTitle": "پیگیری امن درخواست‌ها و نتایج",
  "trader.shellDescription": "این پوسته برای گردش‌های Trader در فاز ۱A آماده شده است.",
  "trader.nav.home": "خانه",
  "trader.nav.requests": "درخواست‌ها",
  "trader.nav.results": "نتایج",
  "trader.nav.notifications": "اعلان‌ها",
  "trader.nav.account": "حساب",
  "admin.appName": "سامانه طلا ـ عملیات داخلی",
  "admin.shellTitle": "صف‌های عملیاتی و کنترل نسخه",
  "admin.shellDescription": "این پوسته هیچ اختیار مالی را در مرورگر ایجاد نمی‌کند.",
  "admin.nav.dashboard": "داشبورد",
  "admin.nav.queues": "صف‌های کاری",
  "admin.nav.traders": "طلافروشان",
  "admin.nav.requests": "درخواست‌های پرداخت",
  "admin.nav.batches": "دسته‌های پرداخت",
  "admin.nav.results": "نتایج بانک",
  "admin.nav.audit": "ممیزی",
  "admin.nav.settings": "تنظیمات",
  "foundation.title": "زیرساخت رابط کاربری M1",
  "foundation.noAuthority": "وضعیت‌های نمایش صرفاً تجربه کاربری‌اند؛ مرجع اختیار، API سمت سرور است.",
  "foundation.statesTitle": "وضعیت‌های پایه",
  "foundation.statesDescription": "حالت‌های بارگذاری، خطا، خالی، عدم دسترسی و تعارض نسخه آماده‌اند.",
  "foundation.apiTitle": "قرارداد ارتباط با API",
  "foundation.apiDescription": "transport مرکزی با ETag، idempotency و خطای استاندارد آماده است.",
  "foundation.securityTitle": "مرز امنیت مرورگر",
  "foundation.securityDescription": "پاسخ‌های API و فایل‌ها ذخیره یا برای استفاده آفلاین کش نمی‌شوند.",
  "foundation.openStates": "مشاهده وضعیت‌های پایه",
  "foundation.requestIdExample": "نمونه شناسه پیگیری",
  "trader.welcome": "خوش آمدید",
  "trader.noData": "در این مرحله داده مالی نمونه نمایش داده نمی‌شود.",
  // Kept, and no longer rendered by the shell. Slice 10D replaced it with the three
  // messages below, which say what is actually known — but the string is left here because
  // `foundation.noAuthority` and the M1 static shell still reference this vocabulary, and
  // deleting a message to prove a screen changed is how a translation file loses history.
  "admin.roleUnknown": "نقش جاری: تعیین‌نشده",
  // What the header says about the session. Three states, because "not signed in" and
  // "still asking" are different facts and a person who sees the first while the second is
  // true will go and sign in again for no reason.
  "admin.session.loading": "در حال شناسایی نشست…",
  "admin.session.anonymous": "وارد نشده‌اید",
  // The identifier rather than a name: `/auth/me` returns no display name, and inventing
  // one — or inferring a role from the permission list — would be the screen asserting
  // something the server never told it.
  "admin.session.signedIn": "شناسه کاربر: {id}",
  "admin.landing.signedInTitle": "شما وارد شده‌اید",
  "admin.landing.signedInBody": "دسترسی‌های شما تعیین‌کنندهٔ بخش‌هایی است که در ناوبری می‌بینید. نبودن یک بخش به معنی نداشتن اختیار آن است، و سرور در هر حال درخواست بدون مجوز را رد می‌کند.",
  "admin.landing.permissionCount": "تعداد دسترسی‌های فعال: {count}",
  "admin.landing.anonymousTitle": "برای ادامه وارد شوید",
  "admin.landing.anonymousBody": "بدون ورود، تنها بخش‌های عمومی نمایش داده می‌شوند.",
  "admin.landing.signIn": "ورود کارکنان",
  "admin.queueTitle": "صف‌های عملیاتی",
  "admin.queueDescription": "محتوای صف‌ها پس از اتصال قراردادهای API و مجوزهای سمت سرور نمایش داده می‌شود.",
  "admin.queue.traderApproval": "تأیید طلافروشان",
  "admin.queue.requestReview": "بررسی درخواست‌های پرداخت",
  "admin.queue.managerApproval": "تأیید نسخه توسط مدیر",
  "admin.queue.bankResult": "نتایج بانک و شواهد",
  "pwa.updateAvailable": "نسخه جدید سامانه آماده است. پس از رسیدن به نقطه امن آن را اعمال کنید.",
  "pwa.applyUpdate": "اعمال نسخه جدید",
  "offline.title": "اتصال شبکه در دسترس نیست",
  "offline.description": "فقط پوسته عمومی در حالت آفلاین قابل مشاهده است. هیچ فرمان مالی در صف قرار نگرفته است.",
  // The trader approval screen. Persian throughout, and the status labels are the
  // operator's vocabulary rather than the column's: pending_approval is a database
  // value, "در انتظار تأیید" is what a person reading a queue understands. Keyed by the
  // stored value so an unmapped status is a compile error rather than a raw column name
  // appearing on screen.
  "admin.traders.title": "طلافروشان",
  "admin.traders.description": "کسب‌وکارهایی که درخواست عضویت داده‌اند. تصمیم شما بلافاصله ثبت و ممیزی می‌شود.",
  "admin.traders.loading": "در حال دریافت فهرست…",
  "admin.traders.empty": "هنوز هیچ کسب‌وکاری درخواست نداده است.",
  "admin.traders.emptyTitle": "فهرست خالی است",
  "admin.traders.failed": "دریافت فهرست ممکن نشد.",
  "admin.traders.failedTitle": "خطا در دریافت",
  "admin.traders.forbiddenTitle": "دسترسی ندارید",
  "admin.traders.forbidden": "حساب شما مجوز مشاهده طلافروشان را ندارد.",
  "admin.traders.name": "نام کسب‌وکار",
  "admin.traders.phone": "شماره تماس",
  "admin.traders.status": "وضعیت",
  "admin.traders.actions": "اقدام",
  "admin.traders.approve": "تأیید",
  "admin.traders.reject": "رد",
  "admin.traders.working": "در حال ثبت…",
  "admin.traders.reasonLabel": "دلیل رد",
  "admin.traders.reasonRequired": "برای رد کردن، نوشتن دلیل الزامی است.",
  "admin.traders.decisionFailed": "ثبت تصمیم ممکن نشد. فهرست را تازه کنید و دوباره تلاش کنید.",
  "admin.traders.staleTitle": "اطلاعات شما قدیمی است",
  "admin.traders.stale": "این کسب‌وکار در این فاصله تغییر کرده است. فهرست تازه شد؛ تصمیم را دوباره بگیرید.",
  "admin.traders.refresh": "تازه‌سازی",
  "status.pending_approval": "در انتظار تأیید",
  "status.approved": "تأییدشده",
  "status.rejected": "ردشده",
  "status.active": "فعال",
  "status.inactive": "غیرفعال",
  "status.suspended": "معلق",
  // The trader's own account screen. What a business sees about itself while it waits,
  // and after the centre decides. Each state says what happens next rather than only
  // naming the state: somebody who has just registered wants to know whether to wait or
  // to act, and "pending" alone answers neither.
  "trader.profile.title": "حساب کسب‌وکار",
  "trader.profile.loading": "در حال دریافت اطلاعات…",
  "trader.profile.failedTitle": "خطا در دریافت",
  "trader.profile.failed": "اطلاعات کسب‌وکار دریافت نشد. لطفاً دوباره تلاش کنید.",
  "trader.profile.refresh": "تلاش دوباره",
  "trader.profile.name": "نام کسب‌وکار",
  "trader.profile.phone": "شماره تماس",
  "trader.profile.legalName": "نام حقوقی",
  "trader.profile.notProvided": "ثبت نشده",
  "trader.profile.pendingTitle": "در انتظار تأیید مرکز",
  "trader.profile.pending": "درخواست شما ثبت شده و در نوبت بررسی مرکز است. تا زمان تأیید امکان انجام معامله وجود ندارد. نیازی به ثبت درخواست دوباره نیست.",
  "trader.profile.approvedTitle": "کسب‌وکار شما تأیید شد",
  "trader.profile.approved": "مرکز کسب‌وکار شما را تأیید کرده است.",
  "trader.profile.rejectedTitle": "درخواست پذیرفته نشد",
  "trader.profile.rejected": "مرکز درخواست عضویت شما را نپذیرفته است. برای پیگیری با مرکز تماس بگیرید.",
  "trader.profile.suspendedTitle": "فعالیت کسب‌وکار معلق است",
  "trader.profile.suspended": "فعالیت کسب‌وکار شما توسط مرکز معلق شده است. برای پیگیری با مرکز تماس بگیرید.",
  // Applying. The screen a goldsmith meets before they have any account at all, which is
  // why it is the only trader screen whose text has to be understandable to somebody who
  // has never seen the platform.
  "trader.register.title": "درخواست همکاری",
  "trader.register.intro": "اطلاعات کسب‌وکار خود را وارد کنید. پس از بررسی مرکز، نتیجه به شما اعلام می‌شود.",
  "trader.register.displayName": "نام کسب‌وکار",
  "trader.register.displayNameHint": "نامی که مرکز با آن شما را می‌شناسد",
  "trader.register.legalName": "نام حقوقی (اختیاری)",
  "trader.register.legalNameHint": "اگر کسب‌وکار شما شخصیت حقوقی ثبت‌شده دارد",
  "trader.register.contactName": "نام و نام خانوادگی مسئول",
  "trader.register.phone": "شماره موبایل",
  "trader.register.phoneHint": "مثل ۰۹۱۲۳۴۵۶۷۸۹ — با ارقام فارسی یا انگلیسی",
  "trader.register.password": "گذرواژه",
  "trader.register.passwordHint": "با همین شماره و گذرواژه وارد می‌شوید.",
  "trader.register.passwordConfirm": "تکرار گذرواژه",
  "trader.register.submit": "ثبت درخواست",
  "trader.register.submitting": "در حال ارسال…",
  // Every reason a field is refused before the request leaves the browser. None of these
  // is a decision the server made — each is this form catching a typo.
  "trader.register.requiredField": "این فیلد الزامی است.",
  "trader.register.invalidPhone": "شماره موبایل معتبر نیست. شماره‌ای مثل ۰۹۱۲۳۴۵۶۷۸۹ وارد کنید.",
  "trader.register.passwordMismatch": "دو گذرواژه یکسان نیستند.",
  "trader.register.problemsTitle": "چند مورد را اصلاح کنید",
  "trader.register.failureTitle": "درخواست ارسال نشد",
  "trader.register.failure": "ارسال درخواست ممکن نشد. لطفاً دوباره تلاش کنید.",
  "trader.register.rateLimited": "تعداد درخواست‌ها زیاد بوده است. کمی بعد دوباره تلاش کنید.",
  // What a person is told afterwards. Deliberately true whether a new application was
  // created or the number was already registered and nothing happened: the endpoint
  // answers identically either way, so a message announcing a new account would be a
  // claim this screen has no way to support.
  "trader.register.doneTitle": "درخواست شما دریافت شد",
  "trader.register.done": "مرکز درخواست شما را بررسی می‌کند. برای دیدن وضعیت، با شماره موبایل و گذرواژه‌ای که ثبت کرده‌اید وارد شوید.",
  "trader.register.goToLogin": "ورود به حساب",
  "trader.register.backToLogin": "قبلاً درخواست داده‌اید؟ وارد شوید.",
} as const;

export type MessageKey = keyof typeof faMessages;

export function t(key: MessageKey): string {
  return faMessages[key];
}
