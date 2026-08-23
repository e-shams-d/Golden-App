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
  // The way out. Both auth adapters have carried a complete `logout` since slice 9 and
  // nothing called it, so a signed-in person could only leave by clearing cookies.
  "common.signOut": "خروج",
  "common.signingOut": "در حال خروج…",
  "common.retry": "تلاش دوباره",
  "common.refresh": "دریافت آخرین اطلاعات",
  "common.backToHome": "بازگشت به صفحه اصلی",
  // For a value the server could not resolve — a bank profile whose row is gone, say. Distinct
  // from a value that is legitimately absent, which gets its own wording where it appears.
  "common.unknown": "نامشخص",
  "common.cancel": "انصراف",
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
  "trader.nav.evidence": "رسیدها",
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
  // The two items whose screens exist. The six above are kept because their screens return
  // with M4–M6 and their wording is already reviewed; the navigation module is what decides
  // which are rendered, and it renders only the ones with a page.
  "admin.nav.staff": "کارکنان",
  "admin.nav.roles": "نقش‌ها و دسترسی‌ها",
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
  // Staff administration. Slice 8E built ten routes and no way to reach them; these are the
  // words for the screen that reaches them.
  "adminUsers.title": "مدیریت کارکنان",
  "adminUsers.description": "حساب‌های کارکنان مرکز، نقش‌هایشان و وضعیت دسترسی. تغییر وضعیت یک حساب، نشست‌های فعال آن را همان لحظه پایان می‌دهد.",
  "adminUsers.listTitle": "حساب‌های موجود",
  "adminUsers.emptyTitle": "هنوز حسابی ساخته نشده",
  "adminUsers.emptyDescription": "با فرم پایین نخستین حساب کارکنان را بسازید.",
  "adminUsers.createTitle": "ساخت حساب جدید",
  "adminUsers.username": "نام کاربری",
  "adminUsers.fullName": "نام و نام خانوادگی",
  "adminUsers.password": "گذرواژهٔ اولیه",
  "adminUsers.role": "نقش",
  "adminUsers.roles": "نقش‌ها",
  "adminUsers.create": "ساخت حساب",
  "adminUsers.created": "حساب {username} ساخته شد.",
  "adminUsers.suspend": "تعلیق",
  "adminUsers.reactivate": "فعال‌سازی دوباره",
  "adminUsers.suspended": "حساب معلق شد و نشست‌های فعالش پایان یافت.",
  "adminUsers.reactivated": "حساب دوباره فعال شد.",
  "adminUsers.resetPassword": "بازنشانی گذرواژه",
  // The temporary password is shown once, here, because the server returns none — that is
  // the obligation. Somebody has to be able to read the value they are about to hand over,
  // and the only place it can be read is where it was chosen.
  "adminUsers.resetDone": "گذرواژهٔ موقت: {password} — آن را به صاحب حساب برسانید. حساب تا زمانی که خودش گذرواژه‌ای انتخاب نکند وارد نمی‌شود.",
  "adminUsers.defaultSuspendReason": "تعلیق از طریق صفحهٔ مدیریت کارکنان",
  "adminUsers.defaultResetReason": "بازنشانی از طریق صفحهٔ مدیریت کارکنان",
  "adminUsers.actionFailed": "این درخواست انجام نشد",
  "adminUsers.genericFailure": "درخواست انجام نشد. لطفاً صفحه را تازه کنید و دوباره تلاش کنید.",
  "adminUsers.status.recoveryRequired": "در انتظار بازیابی",
  "adminUsers.status.deactivated": "غیرفعال‌شده",
  "roles.title": "نقش‌ها و دسترسی‌ها",
  "roles.description": "هر نقش چه کارهایی می‌تواند انجام دهد. ناوبری بر همین اساس تصمیم می‌گیرد کدام بخش‌ها را نشان دهد.",
  // Said plainly rather than hidden behind a disabled button: an editor that could only ever
  // add a permission would teach the reader something false about the platform.
  "roles.readOnlyNotice": "این صفحه فقط نمایشی است. تغییر مجوزهای یک نقش نیازمند احراز هویت مجدد است و حذف مجوز تا زمان تصویب ADR-005 ممکن نیست.",
  "roles.enabled": "فعال",
  "roles.disabled": "غیرفعال",
  "roles.permissionCount": "تعداد مجوزها: {count}",
  "roles.failedTitle": "دریافت نقش‌ها انجام نشد",
  "roles.failed": "فهرست نقش‌ها دریافت نشد. لطفاً دوباره تلاش کنید.",
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
  // The way in. Until now the trader home page offered neither door: a goldsmith arriving
  // at the application had no link to sign in and no link to apply, so the only way past
  // the front page was to know a URL.
  "trader.entry.loading": "در حال بررسی وضعیت ورود…",
  "trader.entry.anonymousTitle": "به سامانه خوش آمدید",
  "trader.entry.anonymousBody": "اگر پیش‌تر درخواست همکاری داده‌اید وارد شوید؛ در غیر این صورت درخواست خود را ثبت کنید تا مرکز بررسی کند.",
  "trader.entry.register": "ثبت درخواست همکاری",
  "trader.entry.signIn": "ورود به حساب",
  "trader.entry.signedInTitle": "شما وارد شده‌اید",
  "trader.entry.signedInBody": "وضعیت کسب‌وکار شما و نتیجهٔ بررسی مرکز در صفحهٔ حساب نمایش داده می‌شود.",
  "trader.entry.openAccount": "مشاهده حساب کسب‌وکار",
  // M5 slice 8. Only the six statuses M5 can reach are here; document 06 defines seventeen,
  // and `paymentRequestStatusLabel` returns the raw value for the rest rather than inventing
  // a translation for a state this release cannot produce.
  "money.unit.IRR": "ریال",
  "money.unit.TOMAN": "تومان",
  "trader.nav.beneficiaries": "ذی‌نفعان",
  "requestStatus.draft": "پیش‌نویس",
  "requestStatus.submitted_to_center": "ارسال‌شده به مرکز",
  "requestStatus.under_accountant_review": "در حال بررسی حسابداری",
  "requestStatus.needs_trader_correction": "نیازمند اصلاح شما",
  "requestStatus.eligible_for_batching": "تأییدشده برای پرداخت",
  "requestStatus.cancelled": "لغوشده",
  "trader.requests.title": "درخواست‌های پرداخت",
  "trader.requests.description":
    "درخواست‌هایی که ثبت کرده‌اید و وضعیت بررسی آنها در مرکز. اگر مرکز درخواستی را برای اصلاح برگردانده باشد، دلیل آن همین‌جا نوشته شده است.",
  "trader.requests.new": "درخواست جدید",
  "trader.requests.loading": "در حال دریافت درخواست‌ها…",
  "trader.requests.failedTitle": "درخواست‌ها دریافت نشد",
  "trader.requests.failed": "ارتباط با سامانه برقرار نشد. لطفاً کمی بعد دوباره تلاش کنید.",
  "trader.requests.emptyTitle": "هنوز درخواستی ثبت نکرده‌اید",
  "trader.requests.empty": "برای شروع، یک درخواست پرداخت جدید ثبت کنید.",
  "trader.requests.beneficiary": "ذی‌نفع",
  "trader.requests.amount": "مبلغ",
  "trader.requests.reviewNote": "پیام مرکز",
  "trader.requests.correct": "اصلاح این درخواست",
  "trader.requests.open": "مشاهده جزئیات",
  "trader.newRequest.title": "درخواست پرداخت جدید",
  "trader.newRequest.description":
    "ذی‌نفع را انتخاب کنید و مبلغ را با واحد آن وارد کنید. تبدیل تومان به ریال در مرکز انجام می‌شود، نه در مرورگر.",
  "trader.newRequest.beneficiary": "ذی‌نفع",
  "trader.newRequest.beneficiaryHint": "فقط ذی‌نفعان فعال شما در این فهرست هستند.",
  "trader.newRequest.amount": "مبلغ",
  "trader.newRequest.unit": "واحد",
  "trader.newRequest.note": "توضیح (اختیاری)",
  "trader.newRequest.submit": "ثبت پیش‌نویس",
  "trader.newRequest.working": "در حال ثبت…",
  "trader.newRequest.needsBeneficiary": "برای ثبت درخواست، اول باید یک ذی‌نفع فعال داشته باشید.",
  "trader.newRequest.addBeneficiary": "افزودن ذی‌نفع",
  "trader.newRequest.amountRequired": "مبلغ را وارد کنید.",
  "trader.newRequest.failed": "درخواست ثبت نشد. مقادیر را بررسی کنید و دوباره تلاش کنید.",
  "trader.request.title": "جزئیات درخواست",
  "trader.request.loading": "در حال دریافت درخواست…",
  "trader.request.failedTitle": "این درخواست دریافت نشد",
  "trader.request.failed": "ممکن است این درخواست وجود نداشته باشد یا متعلق به شما نباشد.",
  "trader.request.status": "وضعیت",
  "trader.request.history": "تاریخچهٔ نسخه‌ها",
  "trader.request.revision": "نسخه",
  "trader.request.current": "نسخهٔ جاری",
  "trader.request.submit": "ارسال به مرکز",
  "trader.request.correctTitle": "اصلاح و ارسال دوباره",
  "trader.request.correctBody":
    "هر اصلاح یک نسخهٔ تازه می‌سازد و نسخه‌های قبلی دست‌نخورده می‌مانند. پس از اصلاح، خودتان آن را به مرکز ارسال می‌کنید.",
  "trader.request.reason": "دلیل اصلاح (اختیاری)",
  "trader.request.saveRevision": "ثبت نسخهٔ جدید",
  "trader.request.stale":
    "این درخواست در فاصلهٔ باز بودن صفحه تغییر کرده است. اطلاعات تازه نمایش داده شد؛ دوباره بررسی کنید.",
  "trader.request.actionFailed": "این عملیات انجام نشد.",
  "trader.request.nothingAllowed": "در وضعیت فعلی، کاری از سمت شما روی این درخواست ممکن نیست.",
  "trader.beneficiaries.title": "ذی‌نفعان",
  "trader.beneficiaries.description":
    "حساب‌هایی که پرداخت به آنها انجام می‌شود. شبای تکراری رد نمی‌شود، اما هشدار داده می‌شود.",
  "trader.beneficiaries.loading": "در حال دریافت ذی‌نفعان…",
  "trader.beneficiaries.failedTitle": "فهرست ذی‌نفعان دریافت نشد",
  "trader.beneficiaries.failed": "ارتباط با سامانه برقرار نشد. کمی بعد دوباره تلاش کنید.",
  "trader.beneficiaries.emptyTitle": "هنوز ذی‌نفعی ثبت نکرده‌اید",
  "trader.beneficiaries.empty": "برای ثبت درخواست پرداخت، اول یک ذی‌نفع اضافه کنید.",
  "trader.beneficiaries.name": "نام",
  "trader.beneficiaries.iban": "شبا",
  "trader.beneficiaries.status": "وضعیت",
  "trader.beneficiaries.addTitle": "افزودن ذی‌نفع",
  "trader.beneficiaries.fullName": "نام کامل",
  "trader.beneficiaries.nationalId": "کد ملی (اختیاری)",
  "trader.beneficiaries.add": "افزودن",
  "trader.beneficiaries.working": "در حال افزودن…",
  "trader.beneficiaries.addFailed": "ذی‌نفع اضافه نشد. نام و شبا را بررسی کنید.",
  "trader.beneficiaries.duplicateTitle": "ذی‌نفع مشابه پیدا شد",
  "trader.beneficiaries.duplicateBody":
    "این ذی‌نفع ثبت شد، اما مشابه موارد زیر است. اگر اشتباه بوده، آن را غیرفعال کنید.",
  "trader.beneficiaries.matchedOn": "شباهت در",
  // M7 screens slice 1. The manager's approval queue and the exact version they decide on.
  // §13.2 and §13.3 of the screen specification name every field; these are their labels.
  "admin.batches.title": "دسته‌های پرداخت در انتظار تأیید",
  "admin.batches.description":
    "هر سطر یک نسخهٔ دقیق است، نه فقط یک دسته. تأیید شما به همان نسخه و همان محتوا گره می‌خورد.",
  "admin.batches.loading": "در حال دریافت صف…",
  "admin.batches.forbiddenTitle": "دسترسی به این صف ندارید",
  "admin.batches.forbidden":
    "برای دیدن دسته‌های در انتظار تأیید، دسترسی لازم به شما داده نشده است.",
  "admin.batches.failedTitle": "صف دریافت نشد",
  "admin.batches.failed": "ارتباط با سامانه برقرار نشد. کمی بعد دوباره تلاش کنید.",
  "admin.batches.emptyTitle": "چیزی در انتظار تأیید نیست",
  "admin.batches.empty": "نسخه‌ای برای تصمیم‌گیری وجود ندارد.",
  "admin.batches.filterAwaiting": "در انتظار تأیید",
  "admin.batches.filterAll": "همه",
  "admin.batches.open": "بررسی و تصمیم",
  "admin.batches.versionLabel": "نسخهٔ",
  "admin.batches.total": "مبلغ کل (ریال)",
  "admin.batches.rowCount": "تعداد سطر",
  "admin.batches.bank": "بانک",
  "admin.batches.sourceAccount": "حساب مبدأ",
  "admin.batches.mappingVersion": "نسخهٔ نگاشت",
  "admin.batches.warningCount": "هشدارها",
  "admin.batches.preparedBy": "آماده‌کننده",
  "admin.batches.finalizedBy": "نهایی‌کننده",
  // A draft has no finalizer, and that is a fact rather than a missing value.
  "admin.batches.notFinalized": "هنوز نهایی نشده",
  "admin.batches.age": "زمان ساخت نسخه",
  // §13.3's mandatory fields. The two that matter most are the finalizer and the
  // separation-of-duty status: they are what tell a manager whether the decision is theirs.
  "admin.approval.title": "تصمیم دربارهٔ نسخهٔ دقیق",
  "admin.approval.loading": "در حال دریافت نسخه…",
  "admin.approval.forbiddenTitle": "دسترسی به این نسخه ندارید",
  "admin.approval.forbidden": "برای دیدن این نسخه دسترسی لازم به شما داده نشده است.",
  "admin.approval.missingTitle": "این نسخه پیدا نشد",
  "admin.approval.missing": "ممکن است این شناسه وجود نداشته باشد یا به این دسته تعلق نداشته باشد.",
  "admin.approval.failedTitle": "این نسخه دریافت نشد",
  "admin.approval.failed": "ارتباط با سامانه برقرار نشد. کمی بعد دوباره تلاش کنید.",
  "admin.approval.mayDecide": "شما می‌توانید دربارهٔ این نسخه تصمیم بگیرید.",
  "admin.approval.mayNotDecide": "شما نمی‌توانید دربارهٔ این نسخه تصمیم بگیرید.",
  "admin.approval.priorDecision": "تصمیم پیشین",
  "admin.approval.batchReference": "شمارهٔ دسته",
  "admin.approval.exactVersion": "نسخهٔ دقیق",
  "admin.approval.immutableStatus": "وضعیت",
  "admin.approval.totalIrr": "مبلغ کل (ریال)",
  "admin.approval.totalToman": "معادل (تومان)",
  "admin.approval.requestCount": "تعداد درخواست",
  "admin.approval.rowCount": "تعداد سطر",
  "admin.approval.traderCount": "تعداد طلافروش",
  "admin.approval.beneficiaryCount": "تعداد ذی‌نفع",
  "admin.approval.bank": "بانک",
  "admin.approval.bankProfileVersion": "نسخهٔ پروفایل بانک",
  "admin.approval.mappingVersion": "نسخهٔ نگاشت",
  "admin.approval.sourceAccount": "حساب مبدأ",
  "admin.approval.preparedBy": "آماده‌کننده",
  "admin.approval.finalizedBy": "نهایی‌کننده",
  "admin.approval.fingerprint": "اثر انگشت محتوا",
  "admin.approval.warnings": "هشدارها",
  "admin.approval.noWarnings": "هشداری ثبت نشده است.",
  "admin.approval.rows": "سطرها، به همان ترتیب فایل",
  "admin.approval.preview": "پیش‌نمایش",
  "admin.approval.previewAvailable": "پیش‌نمایش این نسخه — قابل ارسال نیست",
  "admin.approval.noPreview": "پیش‌نمایشی برای این نسخه ساخته نشده است.",
  // §13.4 to §13.6. The decision itself, and the banner that stops one being taken about a
  // version somebody has already replaced.
  "admin.decide.approve": "تأیید این نسخه",
  "admin.decide.reject": "رد این نسخه",
  "admin.decide.approveTitle": "تأیید نسخهٔ دقیق",
  "admin.decide.approveBody":
    "با تأیید، همین نسخه و همین محتوا برای ارسال به بانک مجاز می‌شود. برای ادامه رمز خود را وارد کنید.",
  "admin.decide.rejectTitle": "رد نسخهٔ دقیق",
  "admin.decide.rejectBody":
    "رد کردن این نسخه را ویرایش نمی‌کند؛ در صورت نیاز بعداً نسخهٔ جایگزین ساخته می‌شود.",
  "admin.decide.reasonLabel": "دلیل رد (اجباری)",
  "admin.decide.passwordLabel": "رمز شما",
  "admin.decide.confirmApprove": "می‌دانم که این تأیید، پرداخت این فایل را مجاز می‌کند.",
  "admin.decide.confirmReject": "می‌دانم که این نسخه رد می‌شود و پرداختی از آن انجام نمی‌شود.",
  "admin.decide.submit": "ثبت تصمیم",
  "admin.decide.working": "در حال ثبت…",
  "admin.decide.recorded": "تصمیم ثبت شد.",
  // The fallback when the server refused without a readable message. The server writes for a
  // person, so its own wording is preferred wherever it gives one.
  "admin.decide.failed": "تصمیم ثبت نشد. رمز را بررسی کنید و دوباره تلاش کنید.",
  // §13.4's five behaviours. The banner is deliberately loud: it is the difference between a
  // manager deciding about what they read and deciding about what replaced it.
  "admin.decide.staleTitle": "این نسخه دیگر نسخهٔ جاری نیست",
  "admin.decide.staleBody":
    "پس از باز شدن این صفحه، نسخهٔ جایگزینی ساخته شده است. تصمیم‌گیری دربارهٔ این نسخه ممکن نیست و صفحه فقط برای سابقه باز مانده.",
  "admin.decide.staleLink": "رفتن به نسخهٔ جاری",
  "admin.requests.title": "درخواست‌های پرداخت",
  "admin.requests.description":
    "صف بررسی حسابداری. تأیید برای پرداخت، تأیید مدیر نیست؛ در این مرحله فقط درستی درخواست بررسی می‌شود.",
  "admin.requests.loading": "در حال دریافت صف…",
  "admin.requests.forbiddenTitle": "دسترسی به این صف ندارید",
  "admin.requests.forbidden":
    "برای دیدن درخواست‌های پرداخت، دسترسی لازم به حساب شما داده نشده است.",
  "admin.requests.failedTitle": "صف دریافت نشد",
  "admin.requests.failed": "ارتباط با سامانه برقرار نشد. کمی بعد دوباره تلاش کنید.",
  "admin.requests.emptyTitle": "چیزی در صف نیست",
  "admin.requests.empty": "درخواستی برای بررسی وجود ندارد.",
  "admin.requests.filterAll": "همه",
  "admin.requests.open": "بررسی",
  "admin.request.title": "بررسی درخواست",
  "admin.request.loading": "در حال دریافت درخواست…",
  "admin.request.failedTitle": "این درخواست دریافت نشد",
  "admin.request.failed": "ممکن است این شناسه وجود نداشته باشد.",
  "admin.request.startReview": "شروع بررسی",
  "admin.request.requestCorrection": "برگرداندن برای اصلاح",
  "admin.request.markEligible": "تأیید برای پرداخت",
  "admin.request.reasonCode": "کد دلیل",
  "admin.request.messageToTrader": "پیام به طلافروش",
  "admin.request.internalNote": "یادداشت داخلی (اختیاری)",
  "admin.request.reviewNote": "یادداشت بررسی (اختیاری)",
  "admin.request.correctionNeedsBoth": "کد دلیل و پیام به طلافروش هر دو لازم است.",
  "admin.request.working": "در حال انجام…",
  "admin.request.stale":
    "این درخواست در فاصلهٔ باز بودن صفحه تغییر کرده است. اطلاعات تازه نمایش داده شد.",
  "admin.request.actionFailed": "این عملیات انجام نشد.",
  "admin.request.notManagerApproval": "این مرحله تأیید مدیر نیست.",
  "admin.request.history": "تاریخچهٔ نسخه‌ها",
} as const;

export type MessageKey = keyof typeof faMessages;

export function t(key: MessageKey): string {
  return faMessages[key];
}

/**
 * A payment-request status as a person reads it, or the raw value if it is one this release
 * cannot produce.
 *
 * Here rather than in each app because both need it and a duplicated label map drifts: the
 * trader would read "نیازمند اصلاح شما" while the accountant read something else for the same
 * row. `UI-ISO-001` is about neither bundle naming the other's endpoints, and a shared word
 * is not an endpoint.
 *
 * The fallback is the raw value on purpose. Document 06 defines seventeen statuses and M5
 * reaches six; returning the code for `batched` is honest about a state this release cannot
 * reach, where a plausible invented translation would be a claim the software cannot support.
 */
export function paymentRequestStatusLabel(status: string): string {
  const key = `requestStatus.${status}`;
  return key in faMessages ? faMessages[key as MessageKey] : status;
}
