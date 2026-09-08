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
  // M11 Screens slice 1. One set of strings for both applications, and that is not a breach of
  // `UI-ISO-001`: the rule is about neither bundle naming the other's *endpoints*, and a shared
  // word is not an endpoint — the same reasoning `paymentRequestStatusLabel` records below. The
  // screens are separate files; only the Persian is shared, because "خوانده شد" means one thing
  // on both sides.
  //
  // `trader.nav.notifications` above predates this slice and had no page behind it. It is left
  // alone rather than reused: the navigation label and the page heading are different strings
  // that happen to match today, and collapsing them would make renaming one rename both.
  "notifications.title": "اعلان‌ها",
  "notifications.nav": "اعلان‌ها",
  "notifications.unreadCount": "خوانده‌نشده",
  "notifications.markRead": "خوانده شد",
  "notifications.markAllRead": "همه را خوانده‌شده کن",
  // Its own empty state rather than `state.empty.*`, which says "record the first one and this
  // section will fill" — advice a person cannot act on here. Nobody creates a notification; the
  // system does. An empty list means nothing has happened, and saying so is the honest text.
  "notifications.emptyTitle": "پیامی ندارید",
  "notifications.emptyDescription": "هر زمان سامانه خبری برای شما داشته باشد، اینجا نمایش داده می‌شود.",
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
  // M11 Screens slice 2. Was "محتوای صف‌ها پس از اتصال قراردادهای API … نمایش داده می‌شود" — an
  // honest placeholder for eleven milestones, and now false: the contracts are connected and the
  // counts are the server's.
  "admin.queueDescription":
    "هر صف، کاری است که منتظر شماست. تعدادها از سرور می‌آید و تنها صف‌هایی را می‌بینید که دسترسی آن را دارید.",
  "admin.queueEmptyTitle": "صفی برای شما نیست",
  "admin.queueEmptyDescription":
    "هیچ‌یک از صف‌های عملیاتی به نقش شما سپرده نشده است. این یعنی کاری در انتظار شما نیست، نه اینکه دسترسی‌تان خطا دارد.",
  "admin.queueFailedTitle": "دریافت صف‌ها انجام نشد",
  "admin.queueFailed": "فهرست صف‌ها دریافت نشد. لطفاً دوباره تلاش کنید.",
  "admin.queueWaiting": "{count} مورد در انتظار",
  "admin.queueOpen": "باز کردن صف",
  // The queue screen itself.
  "queues.rowsTitle": "ردیف‌های صف",
  "queues.reference": "شناسه",
  "queues.status": "وضعیت",
  "queues.createdAt": "زمان ثبت",
  "queues.trader": "طلافروش",
  "queues.noTrader": "—",
  "queues.total": "مجموع در انتظار: {count}",
  "queues.showing": "نمایش {count} ردیف از این صف",
  "queues.emptyTitle": "این صف خالی است",
  "queues.emptyDescription": "در این لحظه کاری در این صف در انتظار نیست.",
  "queues.failedTitle": "دریافت ردیف‌ها انجام نشد",
  "queues.failed": "ردیف‌های این صف دریافت نشد. لطفاً دوباره تلاش کنید.",
  "queues.unknownTitle": "این صف شناخته نشد",
  "queues.unknownDescription":
    "چنین صفی برای نقش شما وجود ندارد. به فهرست صف‌ها بازگردید و یکی را انتخاب کنید.",
  "queues.backToIndex": "بازگشت به فهرست صف‌ها",
  "queues.sortLabel": "ترتیب",
  "queues.filterTrader": "شناسه طلافروش",
  "queues.filterTaskType": "نوع کار",
  "queues.applyFilters": "اعمال",
  "queues.clearFilters": "پاک کردن",
  "queues.nextPage": "صفحه بعد",
  "queues.previousPage": "از ابتدا",
  "queues.sort.created_at": "زمان ثبت",
  "queues.sort.id": "شناسه داخلی",
  // §19.2's sixteen, each named the way an operations person says it rather than the way the URL
  // spells it. A queue in the registry with no label here fails
  // `tests/backend/test_queue_screens_exist.py` — the drift guard, because the list of queues
  // lives in the backend and only the words live here.
  // M11 Screens slice 3. The trader's published payment result — the first time M9's publication
  // reaches the person it is about.
  "result.title": "نتیجه پرداخت",
  "result.backToRequest": "بازگشت به درخواست",
  "result.publishedAt": "زمان انتشار",
  "result.version": "نسخه نتیجه",
  "result.requestStatus": "وضعیت درخواست",
  "result.contentHash": "اثر انگشت محتوا",
  "result.downloadCard": "دریافت کارت نتیجه",
  "result.corrected":
    "این نتیجه اصلاح شده است. نسخه‌ای که می‌بینید آخرین نسخه است و نسخه‌های پیشین جایگزین شده‌اند.",
  "result.acknowledgedAlready": "شما این نتیجه را تأیید کرده‌اید در",
  "result.disputedAlready": "شما به این نتیجه اعتراض کرده‌اید در",
  "result.acknowledge": "تأیید می‌کنم",
  "result.dispute": "اعتراض دارم",
  // Said before the fields, not after the button: doc 05 — "a dispute creates a visible manual
  // review task and does not automatically reverse bank facts".
  "result.disputeReversesNothing":
    "اعتراض شما هیچ تراکنشی را برنمی‌گرداند. یک کار بررسی برای مرکز ساخته می‌شود و نتیجه پس از بررسی به شما اعلام خواهد شد.",
  "result.disputeReason": "دلیل اعتراض",
  "result.disputeDescription": "توضیح شما",
  "result.submitDispute": "ثبت اعتراض",
  "result.cancelDispute": "انصراف",
  // Two options only. The backend deliberately left `reason_code` un-enumerated so a customer
  // whose complaint fits no preset is not turned away, and a dropdown of guessed categories is
  // precisely how that happens. The general one is first and is the default; the specific one is
  // the single value document 05 documents. The complaint itself goes in the description.
  "result.reason.other": "موضوع دیگری است — در توضیح می‌نویسم",
  "result.reason.notReceived": "پول به حساب ذی‌نفع نرسیده است",
  "result.disputeDescriptionHint":
    "به زبان خودتان بنویسید چه چیزی درست نیست. هیچ فهرست از پیش تعیین‌شده‌ای شما را محدود نمی‌کند.",
  "result.absentTitle": "نتیجه‌ای برای این درخواست منتشر نشده است",
  "result.absentDescription":
    "تا زمانی که مرکز نتیجه پرداخت را منتشر نکند چیزی برای نمایش نیست. اگر پرداخت ناموفق بوده باشد، از طریق اعلان‌ها به شما خبر داده می‌شود.",
  "result.failedTitle": "دریافت نتیجه انجام نشد",
  "result.failed": "نتیجه این درخواست دریافت نشد. لطفاً دوباره تلاش کنید.",
  "result.refused":
    "این درخواست پذیرفته نشد. ممکن است وضعیت درخواست از زمانی که صفحه را باز کرده‌اید تغییر کرده باشد؛ اطلاعات به‌روز شد.",
  // 412 on this screen means one specific thing: the centre corrected the result while this
  // person was reading it. That is the event the request's version exists to catch, so it is
  // worth its own sentence rather than a generic refusal.
  "result.stale":
    "نتیجه این پرداخت در همین فاصله اصلاح شد، پس پاسخ شما ثبت نشد. نسخه تازه در بالا نمایش داده شده است؛ اگر با آن موافقید دوباره تأیید کنید.",
  "result.viewResult": "دیدن نتیجه پرداخت",
  // M11 Screens slice 4. The centre's side: what the bank did with one attempt, and what the
  // centre publishes about it.
  "attempt.title": "نتیجه بانکی این تلاش",
  "attempt.number": "شماره تلاش",
  "attempt.status": "وضعیت تلاش",
  "attempt.amount": "مبلغ تلاش (ریال)",
  "attempt.requestStatus": "وضعیت درخواست",
  "attempt.tracking": "شماره پیگیری بانک",
  "attempt.resultAt": "زمان نتیجه بانک",
  "attempt.failureCode": "کد ناموفقی",
  "attempt.failureReason": "شرح ناموفقی",
  "attempt.evidenceUnavailable": "دلیل نبودن مستند",
  "attempt.reason": "دلیل",
  "attempt.revisionId": "شناسه نسخه درخواست",
  "attempt.retryAmount": "مبلغ تلاش تازه (ریال)",
  "attempt.confirmPaid": "ثبت پرداخت موفق",
  "attempt.confirmFailed": "ثبت پرداخت ناموفق",
  "attempt.markRetryRequired": "نیازمند تلاش دوباره",
  "attempt.createRetry": "ساخت تلاش تازه",
  "attempt.submit": "ثبت",
  "attempt.paidNeedsBankFacts":
    "شماره پیگیری و زمان نتیجه، سند خودِ بانک است. ثبت پرداخت موفق بدون آن‌ها ادعایی بدون منبع است.",
  "attempt.retryRequiredCreatesNothing":
    "این کار تلاش تازه‌ای نمی‌سازد؛ فقط ثبت می‌کند که یکی لازم است. ساخت تلاش، تصمیم جداگانه‌ای است.",
  "attempt.retryAmountIsADecision":
    "مبلغ تلاش تازه یک تصمیم است — باقیمانده حل‌نشده — نه تکرار آنچه بانک از قبل دارد.",
  "attempt.failedTitle": "دریافت تلاش انجام نشد",
  "attempt.failed": "اطلاعات این تلاش دریافت نشد. لطفاً دوباره تلاش کنید.",
  "attempt.refused": "این ثبت پذیرفته نشد. اطلاعات به‌روز شد؛ وضعیت تازه را ببینید.",
  // 412 on this screen means one specific thing, and it is worth its own sentence.
  "attempt.stale":
    "همکار دیگری در همین فاصله نتیجه این تلاش را ثبت کرد، پس ثبت شما اعمال نشد. وضعیت تازه در بالا نمایش داده شده است.",
  // The publication side.
  "publication.title": "انتشار نتیجه برای طلافروش",
  "publication.previewFirst": "ابتدا پیش‌نمایش بگیرید تا ببینید طلافروش چه چیزی خواهد دید.",
  "publication.preview": "پیش‌نمایش",
  "publication.publish": "انتشار برای طلافروش",
  "publication.nextVersion": "نسخه‌ای که ساخته می‌شود",
  "publication.contentHash": "اثر انگشت محتوا",
  "publication.messageToTrader": "پیام به طلافروش (اختیاری)",
  "publication.historyTitle": "نسخه‌های منتشرشده",
  "publication.historyEmpty": "هنوز چیزی برای این درخواست منتشر نشده است.",
  "publication.version": "نسخه",
  "publication.status": "وضعیت",
  "publication.publishedAt": "زمان انتشار",
  "publication.failedTitle": "دریافت اطلاعات انتشار انجام نشد",
  "publication.failed": "اطلاعات انتشار دریافت نشد. لطفاً دوباره تلاش کنید.",
  "publication.refused": "این کار پذیرفته نشد. اطلاعات به‌روز شد.",
  "publication.stale":
    "درخواست در همین فاصله تغییر کرد، پس انتشار انجام نشد. اطلاعات تازه را ببینید و در صورت تأیید دوباره منتشر کنید.",
  // The correction flow, and why there is no button for it.
  "publication.correctionBlockedTitle": "اصلاح نتیجه منتشرشده در این نسخه فعال نیست",
  "publication.correctionBlocked":
    "اصلاح یک نتیجه منتشرشده به دو نفر نیاز دارد: یکی آماده می‌کند و دیگری تأیید. این تفکیک هنوز در سطح دسترسی‌ها تصویب نشده و مجوز آن به هیچ نقشی داده نشده است، پس صفحه‌ای هم برای آن ساخته نشده. مسیر بک‌اند آماده است و به محض تصویب، فعال می‌شود.",
  "publication.viewPublication": "انتشار نتیجه",
  // M11 Screens slice 5. Gold orders — the trader files one, the centre prices it.
  "gold.nav": "سفارش‌های طلا",
  "gold.listTitle": "سفارش‌های طلا",
  "gold.listEmptyTitle": "هنوز سفارشی ثبت نشده است",
  "gold.listEmptyDescription": "برای خرید طلا از مرکز، یک سفارش تازه ثبت کنید.",
  "gold.failedTitle": "دریافت سفارش‌ها انجام نشد",
  "gold.failed": "فهرست سفارش‌ها دریافت نشد. لطفاً دوباره تلاش کنید.",
  "gold.newOrder": "سفارش تازه",
  "gold.orderNumber": "شماره سفارش",
  "gold.status": "وضعیت",
  "gold.type": "نوع طلا",
  "gold.weight": "وزن",
  "gold.purity": "عیار",
  "gold.expectedAmount": "مبلغ برآوردی (ریال)",
  "gold.finalAmount": "مبلغ نهایی (ریال)",
  "gold.notPricedYet": "هنوز قیمت‌گذاری نشده",
  "gold.createdAt": "زمان ثبت",
  "gold.open": "باز کردن",
  "gold.detailTitle": "سفارش طلا",
  "gold.backToList": "بازگشت به فهرست سفارش‌ها",
  "gold.detailFailedTitle": "دریافت سفارش انجام نشد",
  "gold.detailFailed": "اطلاعات این سفارش دریافت نشد. لطفاً دوباره تلاش کنید.",
  "gold.submit": "ارسال به مرکز",
  "gold.submitExplains":
    "پس از ارسال، مرکز سفارش را بررسی و قیمت‌گذاری می‌کند. تا پیش از ارسال می‌توانید آن را رها کنید.",
  "gold.refused": "این کار پذیرفته نشد. اطلاعات به‌روز شد؛ وضعیت تازه را ببینید.",
  "gold.stale":
    "این سفارش در همین فاصله تغییر کرد، پس کار شما انجام نشد. وضعیت تازه در بالا نمایش داده شده است.",
  // The new-order form.
  "gold.createTitle": "ثبت سفارش طلا",
  "gold.createExplains":
    "وزن و عیار را همان‌طور که با مرکز توافق کرده‌اید وارد کنید. قیمت را مرکز تعیین می‌کند.",
  "gold.typeHint": "مثلاً شمش یا آبشده",
  "gold.weightHint": "عدد را با اعشار وارد کنید؛ همان‌طور که می‌نویسید ارسال می‌شود",
  "gold.unit": "واحد وزن",
  "gold.create": "ثبت سفارش",
  "gold.createFailed": "ثبت سفارش انجام نشد. مقادیر را بررسی کنید و دوباره تلاش کنید.",
  // The centre's pricing workspace.
  "pricing.title": "قیمت‌گذاری سفارش",
  "pricing.currentTitle": "قیمت‌گذاری فعلی",
  "pricing.none": "هنوز قیمتی برای این سفارش ثبت نشده است.",
  "pricing.version": "نسخه",
  "pricing.method": "روش",
  "pricing.unitPrice": "قیمت واحد (ریال)",
  "pricing.expectedAmount": "مبلغ برآوردی (ریال)",
  "pricing.contentHash": "اثر انگشت محتوا",
  "pricing.supersededAt": "جایگزین‌شده در",
  "pricing.newTitle": "ثبت قیمت تازه",
  "pricing.explains":
    "هر قیمت‌گذاری یک نسخه تازه می‌سازد و نسخه پیشین جایگزین می‌شود. مبلغ برآوردی را سرور از وزن و قیمت واحد حساب می‌کند.",
  "pricing.note": "یادداشت (اختیاری)",
  "pricing.submit": "ثبت قیمت‌گذاری",
  "pricing.refused": "قیمت‌گذاری پذیرفته نشد. اطلاعات به‌روز شد.",
  // M11 Screens slice 9. The review queue item, and the four decisions about it.
  "task.title": "کار بررسی",
  "task.status": "وضعیت",
  "task.type": "نوع کار",
  "task.assignedTo": "مسئول",
  "task.unassigned": "هنوز به کسی سپرده نشده",
  "task.subject": "موضوع",
  "task.resolution": "نتیجه",
  "task.assignTitle": "سپردن به یک نفر",
  "task.assignee": "مسئول",
  "task.chooseAssignee": "یک نفر را انتخاب کنید",
  "task.assign": "سپردن",
  "task.start": "شروع کار",
  "task.resolveTitle": "ثبت نتیجه",
  "task.resolutionCode": "نوع نتیجه",
  "task.chooseResolution": "یک گزینه را انتخاب کنید",
  "task.resolutionNote": "توضیح (اختیاری)",
  "task.resolve": "ثبت نتیجه",
  "task.cancelTitle": "لغو کار",
  "task.cancelExplains":
    "لغو، کار را بدون تصمیم‌گیری می‌بندد. اگر بررسی انجام شده و نتیجه‌ای دارد، به‌جای لغو نتیجه را ثبت کنید.",
  "task.cancelReason": "دلیل لغو",
  "task.cancel": "لغو کار",
  "task.failedTitle": "دریافت کار انجام نشد",
  "task.loadFailed": "اطلاعات این کار دریافت نشد. لطفاً دوباره تلاش کنید.",
  "task.refused": "این کار پذیرفته نشد. اطلاعات به‌روز شد؛ وضعیت تازه را ببینید.",
  "task.stale":
    "همکار دیگری در همین فاصله درباره این کار تصمیم گرفت، پس کار شما ثبت نشد. وضعیت تازه در بالا نمایش داده شده است.",
  // M11 Screens slice 7. Handing the gold over, and closing the order.
  "dispatch.title": "تحویل طلا",
  "dispatch.type": "نوع تحویل",
  "dispatch.weight": "وزن تحویل‌شده (اختیاری)",
  "dispatch.recipient": "تحویل‌گیرنده (اختیاری)",
  "dispatch.record": "ثبت تحویل",
  "dispatch.confirmedTotal": "مبلغ نهایی سفارش (ریال)",
  "dispatch.expectedAmount": "مبلغ برآوردی سفارش (ریال)",
  // Said above the field, not below the button: filling it changes what the system allows.
  "dispatch.override": "دلیل نادیده‌گرفتن شرط پرداخت (فقط در صورت لزوم)",
  "dispatch.overrideExplains":
    "اگر مبلغ سفارش کامل پرداخت نشده باشد، تحویل پذیرفته نمی‌شود. با نوشتن دلیل، تحویل انجام می‌شود و همین دلیل به‌همراه زمان آن ثبت می‌ماند تا بعداً قابل بازبینی باشد. اگر لازم نیست، خالی بگذارید.",
  "dispatch.closeTitle": "بستن سفارش",
  "dispatch.closeExplains":
    "بستن سفارش کار دیگری است و دسترسی دیگری می‌خواهد؛ لزوماً همان کسی که طلا را تحویل داده آن را نمی‌بندد.",
  "dispatch.closureNote": "یادداشت بستن (اختیاری)",
  "dispatch.close": "بستن سفارش",
  // The trader's side.
  "dispatch.acknowledgeTitle": "تأیید دریافت طلا",
  "dispatch.acknowledgeExplains":
    "با تأیید، اعلام می‌کنید طلا به دست شما رسیده است. اگر چیزی درست نیست، پیش از تأیید با مرکز تماس بگیرید.",
  "dispatch.acknowledge": "دریافت کردم",
  "dispatch.acknowledged": "دریافت طلا تأیید شد.",
  "dispatch.refused": "این کار پذیرفته نشد. اطلاعات به‌روز شد؛ وضعیت تازه را ببینید.",
  // M11 Screens slice 6. The trader claims a payment; the centre matches and confirms it.
  "receipt.claimTitle": "اعلام پرداخت",
  "receipt.claimExplains":
    "اگر مبلغ این سفارش را واریز کرده‌اید، اینجا اعلام کنید. مرکز آن را با صورتحساب بانکی تطبیق می‌دهد و نتیجه را به شما اعلام می‌کند.",
  "receipt.amount": "مبلغ واریزی (ریال)",
  "receipt.tracking": "شماره پیگیری (اختیاری)",
  "receipt.senderName": "نام واریزکننده (اختیاری)",
  "receipt.sourceBank": "بانک مبدأ (اختیاری)",
  "receipt.paymentDate": "تاریخ واریز (اختیاری)",
  "receipt.optionalHelps":
    "پر کردن این موارد اختیاری است و پیدا کردن تراکنش شما را برای مرکز آسان‌تر می‌کند.",
  "receipt.submit": "ثبت اعلام پرداخت",
  "receipt.submitted": "اعلام پرداخت شما ثبت شد. پس از بررسی مرکز، نتیجه اعلام می‌شود.",
  "receipt.failed": "ثبت اعلام پرداخت انجام نشد. مقادیر را بررسی کنید و دوباره تلاش کنید.",
  // The centre's review screen.
  "receipt.reviewTitle": "بررسی اعلام پرداخت",
  "receipt.status": "وضعیت",
  "receipt.claimedAmount": "مبلغ اعلام‌شده (ریال)",
  "receipt.confirmedAmount": "مبلغ تأییدشده (ریال)",
  "receipt.notConfirmedYet": "هنوز تأیید نشده",
  "receipt.orderStatus": "وضعیت سفارش",
  "receipt.createdAt": "زمان اعلام",
  "receipt.matchesTitle": "نامزدهای تطبیق",
  "receipt.matchesEmpty":
    "هنوز هیچ ردیفی برای این اعلام پیشنهاد نشده است. شناسه ردیف صورتحساب را وارد کنید تا پیشنهاد ثبت شود.",
  "receipt.matchStatus": "وضعیت",
  "receipt.matchRow": "ردیف صورتحساب",
  "receipt.matchReasons": "دلایل",
  "receipt.matchRejectedAt": "زمان رد",
  "receipt.matchRejectionReason": "دلیل رد",
  "receipt.propose": "پیشنهاد تطبیق",
  "receipt.proposeRowId": "شناسه ردیف صورتحساب",
  "receipt.proposeReason": "دلیل (اختیاری)",
  "receipt.reject": "رد این پیشنهاد",
  "receipt.rejectReason": "دلیل رد",
  "receipt.rejectExplains":
    "رد کردن، پیشنهاد را پاک نمی‌کند؛ در تاریخچه می‌ماند تا تصمیم‌ها قابل بازبینی بماند.",
  "receipt.confirmTitle": "تأیید دریافت پول",
  "receipt.confirmExplains":
    "مبلغی را که واقعاً رسیده است وارد کنید؛ ممکن است از مبلغ اعلام‌شده کمتر باشد. تأیید بیش از مبلغ سفارش پذیرفته نمی‌شود و یک کار بررسی ساخته می‌شود.",
  "receipt.confirmAmount": "مبلغ تأییدشده (ریال)",
  "receipt.confirmNote": "یادداشت (اختیاری)",
  "receipt.confirm": "تأیید دریافت",
  "receipt.confirmedTotal": "جمع تأییدشده تا این لحظه (ریال)",
  "receipt.expectedAmount": "مبلغ سفارش (ریال)",
  "receipt.failedTitle": "دریافت اطلاعات انجام نشد",
  "receipt.loadFailed": "اطلاعات این اعلام دریافت نشد. لطفاً دوباره تلاش کنید.",
  "receipt.refused": "این کار پذیرفته نشد. اطلاعات به‌روز شد؛ وضعیت تازه را ببینید.",
  "receipt.stale":
    "این اعلام در همین فاصله تغییر کرد، پس کار شما انجام نشد. وضعیت تازه در بالا نمایش داده شده است.",
  "pricing.stale":
    "همکار دیگری در همین فاصله این سفارش را قیمت‌گذاری کرد، پس قیمت شما ثبت نشد. نسخه تازه در بالا نمایش داده شده است.",
  "queue.new-requests": "درخواست‌های جدید",
  "queue.correction-responses": "پاسخ‌های اصلاح",
  "queue.eligible-for-batching": "آماده دسته‌بندی",
  "queue.draft-invalid-batch-versions": "نسخه‌های پیش‌نویس یا نامعتبر",
  "queue.approved-exports-awaiting-send": "فایل‌های تأییدشده در انتظار ارسال به بانک",
  "queue.sent-attempts-awaiting-result": "ارسال‌شده‌ها در انتظار نتیجه",
  "queue.unresolved-bundles-segments": "بسته‌های نتیجه حل‌نشده",
  "queue.failed-partial-retry-payments": "پرداخت‌های ناموفق و نیازمند تلاش دوباره",
  "queue.incoming-receipts-requiring-review": "رسیدهای ورودی نیازمند بررسی",
  "queue.trader-disputes": "اعتراض‌های طلافروشان",
  "queue.reconciliation-tasks": "کارهای مغایرت‌گیری",
  "queue.batch-versions-awaiting-approval": "نسخه‌های دسته در انتظار تأیید",
  "queue.orders-ready-for-dispatch": "سفارش‌های آماده تحویل",
  "queue.blocked-dispatches": "تحویل‌های متوقف‌شده",
  "queue.receipt-confirmation-work": "تأیید رسید تحویل",
  "queue.quarantined-files-exports": "فایل‌های قرنطینه‌شده",
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
  // §14 — the bank file. The screens for an artifact that leaves the platform and becomes a
  // payment somewhere else, which is why so much of this text is about what a screen is *not*
  // telling you.
  "admin.export.title": "فایل بانکی",
  "admin.export.loading": "در حال دریافت اطلاعات فایل…",
  "admin.export.forbiddenTitle": "دسترسی به فایل‌های بانکی ندارید",
  "admin.export.forbidden":
    "خواندن فایل بانکی مجوز جداگانه دارد، چون این فایل فهرست کامل پرداخت‌های مرکز است.",
  "admin.export.missingTitle": "این فایل پیدا نشد",
  "admin.export.missing": "فایلی با این شناسه وجود ندارد یا حذف نشده اما دیگر در دسترس شما نیست.",
  "admin.export.failedTitle": "اطلاعات فایل دریافت نشد",
  "admin.export.failed": "ارتباط با سرور برقرار نشد. دوباره تلاش کنید.",
  // §14.1. The English marker beside this is rendered verbatim from the specification; this is
  // what it means, which is the part that changes what somebody does next.
  "admin.export.previewExplanation":
    "این یک پیش‌نمایش است، نه فایل نهایی. برای بررسی ساخته شده و مجاز به ارسال به بانک نیست؛ ثبت «ارسال شد» برای آن ممکن نیست و مجموع کنترلی آن، مجموع کنترلی رسمی هیچ فایلی نیست.",
  "admin.export.reference": "شمارهٔ فایل",
  "admin.export.fileName": "نام فایل",
  "admin.export.state": "وضعیت",
  "admin.export.kind": "نوع",
  "admin.export.kindPreview": "پیش‌نمایش",
  "admin.export.kindFinal": "نهایی",
  "admin.export.batch": "دستهٔ پرداخت",
  "admin.export.exactVersion": "نسخهٔ دقیق",
  "admin.export.checksum": "مجموع کنترلی فایل",
  // §14.1's second prohibition, done by labelling. A preview's checksum is a real checksum; it is
  // simply not the official checksum of anything that may be sent.
  "admin.export.checksumPreview": "مجموع کنترلی (غیررسمی — پیش‌نمایش)",
  "admin.export.approvalMatch": "تطابق با تأییدیه",
  "admin.export.matchHolds": "محتوای فایل با نسخهٔ تأییدشده یکی است",
  "admin.export.matchBroken": "محتوای فایل با نسخهٔ تأییدشده یکی نیست",
  "admin.export.matchNotApplicable": "موضوعیت ندارد (پیش‌نمایش تأییدیه‌ای ندارد)",
  "admin.export.rowCount": "تعداد سطر",
  "admin.export.total": "مبلغ کل (ریال)",
  "admin.export.bank": "بانک",
  "admin.export.sourceAccount": "حساب مبدأ",
  "admin.export.mapping": "نسخهٔ نقشهٔ ستون‌ها",
  "admin.export.bankProfileVersion": "نسخهٔ پروفایل بانک",
  "admin.export.generationTime": "زمان ساخت",
  "admin.export.generatedBy": "سازنده",
  "admin.export.integrityState": "وضعیت صحت",
  "admin.export.integrityHolds": "هر هشت بررسی برقرار است",
  "admin.export.integrityFailing": "بررسی‌هایی برقرار نیست",
  "admin.export.integrityQuarantined": "قرنطینه‌شده",
  "admin.export.integrityNotApplicable": "موضوعیت ندارد (پیش‌نمایش بررسی نمی‌شود)",
  "admin.export.lastDownloaded": "آخرین دانلود",
  "admin.export.neverDownloaded": "دانلود نشده",
  // S-6, said where an accountant will look rather than only in the plan.
  "admin.export.generatorVersionAbsent":
    "نسخهٔ سازندهٔ فایل ثبت نمی‌شود. اگر دو فایل بانکی ظاهر متفاوتی دارند، سامانه فعلاً نمی‌تواند بگوید با چه نسخه‌ای از تولیدکننده ساخته شده‌اند.",
  // §14.5. Four of its five requirements; the fifth needs a task table Phase 1A does not have.
  "admin.export.quarantinedTitle": "این فایل قرنطینه شده است",
  "admin.export.quarantinedBody":
    "محتوای فایل با آنچه ثبت شده یکی نیست. دانلود برای ارسال به بانک و ثبت «ارسال شد» هر دو بسته‌اند. این فایل مدرک است، نه چیزی که به بانک برود؛ برای جایگزینی باید نسخهٔ تأییدشده دوباره تولید شود.",
  "admin.export.failedChecks": "بررسی‌هایی که برقرار نبود",
  "admin.export.failedChecksUnavailable":
    "این فایل زمانی قرنطینه شده که یکی از بررسی‌ها برقرار نبود، اما در این لحظه همهٔ بررسی‌ها برقرارند. این خودش موضوعی است که باید بررسی شود — فایل بین دو بررسی تغییر کرده است.",
  // §14.6 and §14.7. The English sentence beside this one is rendered verbatim from the
  // specification; this is the same thing said to the person who has to act on it.
  // `15_Agent_Implementation_Plan.md:989` makes this the milestone's central human-factors risk.
  "admin.export.downloadIsNotSending":
    "دانلود کردن این فایل به این معنا نیست که به بانک ارسال شده است. تا وقتی ارسال را ثبت نکنید، سامانه این پرداخت را انجام‌نشده می‌داند — و در تطبیق بعدی دنبال پرداختی می‌گردد که شما انجامش داده‌اید.",
  "admin.export.download": "دانلود فایل",
  "admin.export.markSent": "ثبت ارسال به بانک",
  "admin.export.markSentTitle": "ثبت ارسال همین فایل",
  "admin.export.markSentBody":
    "این ثبت، اظهار شماست که همین فایل را به بانک داده‌اید. سامانه با بانک تماس نمی‌گیرد و نمی‌تواند این را بررسی کند؛ پس مشخصات زیر را ببینید و مطمئن شوید همین فایل است.",
  "admin.export.batchAndVersion": "دسته و نسخه",
  "admin.export.checksumAndIntegrity": "مجموع کنترلی و صحت",
  "admin.export.bankAndSourceAccount": "بانک و حساب مبدأ",
  "admin.export.channelLabel": "از چه راهی ارسال شد؟",
  "admin.export.channel.bank_portal_manual_upload": "بارگذاری دستی در سامانهٔ بانک",
  "admin.export.channel.bank_branch_in_person": "تحویل حضوری در شعبه",
  "admin.export.channel.secure_email_to_bank": "ایمیل امن به بانک",
  "admin.export.noteLabel": "توضیح (اختیاری)",
  "admin.export.markSentAffirmation":
    "تأیید می‌کنم که همین فایل را به بانک داده‌ام. این یک اظهار از طرف من است.",
  "admin.export.markSentSubmit": "ثبت ارسال",
  "admin.export.markSentWorking": "در حال ثبت…",
  "admin.export.markSentFailed": "ثبت ارسال انجام نشد. صفحه را تازه کنید و دوباره تلاش کنید.",
  "admin.export.alreadySent": "ارسال این فایل قبلاً ثبت شده است",
  // §2.5's reminder. The question it answers: who has a copy of this and has not told us they
  // sent it.
  "admin.export.awaitingTitle": "این فایل دانلود شده و ارسالش ثبت نشده",
  "admin.export.awaitingBody":
    "کسی این فایل را برداشته اما ارسال به بانک را ثبت نکرده است. اگر ارسال شده، همین حالا ثبتش کنید؛ اگر نشده، بدانید که سامانه این پرداخت را انجام‌نشده می‌داند.",
  // §14.3's eight canonical states, from `status_catalog.yaml`'s `bank_export` aggregate.
  "admin.export.status.generating": "در حال ساخت",
  "admin.export.status.generated": "ساخته‌شده",
  "admin.export.status.validated": "بررسی‌شده",
  "admin.export.status.downloaded": "دانلودشده",
  "admin.export.status.sent_to_bank_marked": "ارسال به بانک ثبت شده",
  "admin.export.status.voided": "باطل‌شده",
  "admin.export.status.quarantined": "قرنطینه‌شده",
  "admin.export.status.generation_failed": "ساخت ناموفق",
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
  // The bank-result queue, `05_API_Specification.md:1676`. The workspace's way in: nobody
  // memorises a bundle id, so a review screen with no queue is a review screen nobody opens.
  "admin.bundles.title": "نتایج بانکی",
  "admin.bundles.explanation":
    "فایل‌هایی که بانک فرستاده و باید بررسی شوند. آن‌هایی که کار حل‌نشدهٔ بیشتری دارند بالاتر می‌آیند.",
  "admin.bundles.loading": "در حال دریافت فهرست…",
  "admin.bundles.empty": "بستهٔ بازبینی‌نشده‌ای نیست",
  "admin.bundles.emptyExplanation": "هر نتیجه‌ای که بانک فرستاده بررسی شده است.",
  "admin.nav.bankResults": "نتایج بانکی",
  // §16.3 — the bank-result review workspace. The screen where a person looks at what the bank
  // sent and cuts out the part that proves one payment.
  "admin.workspace.title": "بررسی نتیجهٔ بانک",
  "admin.workspace.loading": "در حال دریافت اطلاعات بسته…",
  "admin.workspace.forbiddenTitle": "دسترسی به نتایج بانکی ندارید",
  "admin.workspace.forbidden":
    "خواندن نتیجهٔ بانک مجوز جداگانه دارد، چون این پرونده حساب کامل پرداخت‌های مرکز است.",
  "admin.workspace.missingTitle": "این بسته پیدا نشد",
  "admin.workspace.missing": "بسته‌ای با این شناسه وجود ندارد یا دیگر در دسترس شما نیست.",
  "admin.workspace.failedTitle": "اطلاعات بسته دریافت نشد",
  "admin.workspace.failed": "ارتباط با سرور برقرار نشد. دوباره تلاش کنید.",
  "admin.workspace.summary": "خلاصهٔ بسته",
  "admin.workspace.reference": "شمارهٔ بسته",
  "admin.workspace.state": "وضعیت",
  "admin.workspace.sourceType": "منبع",
  "admin.workspace.segments": "قطعه‌ها",
  "admin.workspace.resolved": "حل‌شده",
  "admin.workspace.unresolved": "حل‌نشده",
  "admin.workspace.gotoUnresolved": "رفتن به حل‌نشدهٔ بعدی",
  "admin.workspace.noUnresolved": "قطعهٔ حل‌نشده‌ای نمانده است.",
  "admin.workspace.files": "فایل‌های بسته",
  "admin.workspace.selectFile": "انتخاب فایل",
  // The honest answer for a spreadsheet. §1.4 of the M8 plan: doc 08 asks for an Excel row preview
  // "where a deterministic parser exists" and none does, so the screen says so rather than showing
  // an empty frame that looks broken.
  "admin.workspace.noPreview": "این فایل صفحه‌ای برای نمایش ندارد",
  "admin.workspace.noPreviewExplanation":
    "پیش‌نمایش سطرهای فایل‌های صفحه‌گسترده هنوز ساخته نشده، چون خوانندهٔ قطعی‌ای برای قالب آن‌ها تأیید نشده است. برای این فایل می‌توانید کل آن را به‌عنوان مدرک پیوست کنید.",
  "admin.workspace.page": "صفحه",
  "admin.workspace.ofPages": "از",
  "admin.workspace.previousPage": "صفحهٔ قبل",
  "admin.workspace.nextPage": "صفحهٔ بعد",
  "admin.workspace.rotateClockwise": "چرخش ساعتگرد",
  "admin.workspace.rotateAnticlockwise": "چرخش پادساعتگرد",
  "admin.workspace.rotation": "زاویهٔ نمایش",
  "admin.workspace.zoomIn": "بزرگ‌نمایی",
  "admin.workspace.zoomOut": "کوچک‌نمایی",
  "admin.workspace.zoomReset": "اندازهٔ اصلی",
  "admin.workspace.zoomLevel": "بزرگ‌نمایی",
  // The crop. §16.3's "rectangular crop selection" and "keyboard-accessible controls" — the second
  // is why every edge has a number input beside it.
  "admin.workspace.crop": "انتخاب ناحیه",
  "admin.workspace.cropLeft": "فاصله از لبهٔ چپ تصویر (X)",
  "admin.workspace.cropTop": "فاصله از لبهٔ بالا (Y)",
  "admin.workspace.cropWidth": "عرض",
  "admin.workspace.cropHeight": "ارتفاع",
  "admin.workspace.cropHint":
    "با کلیدهای جهت‌دار ناحیه را جابه‌جا کنید؛ با Shift ده برابر، و با Alt لبهٔ مربوط تغییر اندازه می‌دهد.",
  "admin.workspace.normalized": "مختصات نرمال‌شده",
  "admin.workspace.normalizedExplanation":
    "این چهار عدد بین صفر و یک هستند و همراه زاویهٔ نمایش ذخیره می‌شوند، تا همین ناحیه بعداً دقیقاً دوباره ساخته شود.",
  "admin.workspace.rasterSize": "اندازهٔ تصویر رندرشده",
  "admin.workspace.createCrop": "ثبت این ناحیه به‌عنوان مدرک",
  "admin.workspace.cropAccepted": "ناحیه ثبت شد و تصویرش در حال ساخته شدن است.",
  "admin.workspace.cropFailed": "ثبت ناحیه انجام نشد.",
  // Selected-segment fields: what a person read off the receipt, typed by them.
  "admin.workspace.fields": "اطلاعات خواندنی از رسید",
  "admin.workspace.beneficiary": "نام ذی‌نفع",
  "admin.workspace.iban": "شبا مقصد",
  "admin.workspace.amount": "مبلغ (ریال)",
  "admin.workspace.tracking": "کد پیگیری",
  "admin.workspace.fieldsOptional": "پر کردن این فیلدها اختیاری است؛ مدرک ناقص هم مدرک است.",
  // The fallback. §16.3's last item, and §16 :1069's last test.
  "admin.workspace.external": "پیوست کل فایل به‌عنوان مدرک",
  "admin.workspace.externalExplanation":
    "اگر این فایل قابل نمایش نیست یا ناحیه‌ای از آن جدا نمی‌شود، می‌توانید کل فایل را به‌عنوان مدرک ثبت کنید.",
  "admin.workspace.externalConfirm": "ثبت کل فایل",
  "admin.workspace.externalAccepted": "کل فایل به‌عنوان مدرک ثبت شد.",
  "admin.workspace.externalFailed": "ثبت مدرک انجام نشد.",
  "admin.workspace.cancel": "انصراف",
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

/**
 * A queue's name as an operations person says it, or the URL segment if there is no label.
 *
 * M11 Screens slice 2. The **set** of queues is the backend's — `GET /api/v1/queues` returns the
 * ones a session may open — and only the words are here. That split is deliberate: a screen holding
 * its own list of sixteen queues would drift from the registry, and a registry holding Persian
 * strings would put translation in a module about permissions.
 *
 * Runtime lookup rather than `t()` for the same reason `paymentRequestStatusLabel` is: the key is
 * a value from the server, so it cannot be checked against `MessageKey` at compile time. What
 * checks it is `tests/backend/test_queue_screens_exist.py`, which reads `BUILT` and fails on a
 * queue with no label — so the fallback is a safety net rather than the plan.
 *
 * The fallback is the raw segment on purpose. `blocked-dispatches` is worse to read than
 * «تحویل‌های متوقف‌شده» and far better than a translation invented for a queue whose meaning
 * nobody here has checked.
 */
export function queueLabel(queue: string): string {
  const key = `queue.${queue}`;
  return key in faMessages ? faMessages[key as MessageKey] : queue;
}

/**
 * A sortable field as a person reads it, or the field name.
 *
 * The sort allowlist comes from the server too — each queue publishes its own — so the same
 * runtime-lookup shape applies. There are two names across all sixteen queues today; a third
 * arrives as a field, not as a screen change.
 */
export function queueSortLabel(field: string): string {
  const key = `queues.sort.${field}`;
  return key in faMessages ? faMessages[key as MessageKey] : field;
}
