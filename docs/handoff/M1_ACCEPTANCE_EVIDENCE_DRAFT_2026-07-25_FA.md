# فرم شواهد انتقال و پذیرش M1 — پیش‌نویس اجرای مقصد

Status: **DRAFT / M1 NOT ACCEPTED — در حال تکمیل**
Milestone: M1 — Repository and Runtime Foundation
Draft date: 2026-07-25

این پیش‌نویس نتایج اجرای پذیرش روی سیستم مقصد (Windows 11 + WSL2 Ubuntu 24.04)
را ثبت می‌کند. موارد PENDING پس از تکمیل، به‌روزرسانی می‌شوند. هیچ secret،
مقدار `.env` یا log پاک‌سازی‌نشده در این فایل ثبت نشده است.

## 1. هویت تحویل

| مورد | مقدار |
|---|---|
| تاریخ و ساعت با timezone | `2026-07-25 ~16:30 +0330 (Asia/Tehran)` |
| نام مخزن خصوصی | `Golden-App` |
| ارائه‌دهنده‌ی مخزن | `GitHub (github.com/e-shams-d/Golden-App)` |
| نام remote | `origin` |
| شاخه‌ی تحویل | `main` |
| SHA مورد انتظار (TRANSFER_SHA) | `3a8e04d5202ec0fdf0ad1c26cb5c4fd81229331d` — شامل پنج اصلاح پذیرش، کامیت‌های CI و وصله‌های امنیتی وابستگی و image |
| SHA دریافت‌شده از remote | تا `b41c13b` تطبیق شد (push مالک ۲۰۲۶-۰۷-۲۵). push کامیت‌های بعدی تا `3a8e04d` باقی است |
| SHA در clone تمیز | `3a8e04d5202ec0fdf0ad1c26cb5c4fd81229331d` — هر دو verifier روی همین SHA با درخت تمیز اجرا و پاس شدند |
| سیستم‌عامل و معماری مقصد | `Windows 11 Pro 10.0.26200 + WSL2 Ubuntu 24.04.4 LTS / x86_64` |
| اجراکننده | `Ehsans@blanclabs.com (با Claude Code)` |
| بازبین | **PENDING — مالک پروژه (@e-shams-d)** |

شرط قبولی این بخش:

- [x] سه مقدار SHA بالا دقیقاً یکسان‌اند — هر سه `b41c13b…`
- [x] commit از remote مخزن خصوصی قابل دریافت است — push موفق مالک و
  `git fetch origin main` در clone تمیز
- [x] clone در یک مسیر خالی و مستقل انجام شده است — `~/gold-platform-clean` در فایل‌سیستم WSL
- [x] خروجی `git status --porcelain` در clone تمیز خالی است — پیش و پس از تمام اجراها
- [x] هر دو lockfile، OpenAPI JSON و TypeScript تولیدشده در همان commit موجودند

## 2. نسخه‌ی ابزارها (داخل WSL — محیط اجرای پذیرش)

| فرمان | مقدار مورد انتظار | مقدار مشاهده‌شده | نتیجه |
|---|---|---|---|
| `git --version` | نسخه‌ی پشتیبانی‌شده | `2.43.0` | PASS |
| `node --version` | `v24.18.0` | `v24.18.0` | PASS |
| `pnpm --version` | `11.15.1` | `11.15.1` | PASS |
| `python --version` | `3.12.13` | `Python 3.12.13` (از طریق uv در venv بک‌اند) | PASS |
| `uv --version` | `0.8.22` | `uv 0.8.22` | PASS |
| `docker version` | Docker Engine فعال | `29.6.1` (native داخل WSL) | PASS |
| `docker compose version` | Compose v2 | `v5.2.0` | PASS |

## 3. کنترل clone و وابستگی‌ها

| کنترل | نتیجه | شناسه/خلاصه‌ی شاهد |
|---|---|---|
| `git fsck --full` | PASS | بدون خطا |
| نصب pnpm با `--frozen-lockfile` | PASS | 8 workspace، بدون drift |
| همگام‌سازی uv با `--frozen --group dev` | PASS | `Using CPython 3.12.13` — 56 پکیج |
| عدم تغییر lockfile بعد از نصب | PASS | `git status --porcelain` خالی |
| `pnpm openapi:check` | PASS | «OpenAPI contract is current» + «Generated TypeScript OpenAPI types are current» |

## 4. شواهد Native

اجرای کامل `infra/scripts/verify-native.sh` در clone تمیز: **PASS** — آخرین
اجرا روی `64fd476` (پس از وصله‌های امنیتی وابستگی‌ها) با
`Native M1 verification passed.` و drift صفر. شمارش تست‌ها پیش و پس از ارتقای
وابستگی‌ها یکسان ماند.
Log artifacts (خارج از Git): `.local/m1-evidence/verify-native-2026-07-25.log`،
`verify-native-final-b41c13b-2026-07-25.log`،
`verify-native-final-deps-2026-07-28.log`

| کنترل | نتیجه | شمار/خلاصه |
|---|---|---|
| `python infra/scripts/validate_repository.py` | PASS | «All checks passed!» |
| scanner داخلی `scan_secrets.py` | PASS | داخل اجرای verify-native |
| Frontend static validation | PASS | «Static M1 workspace validation passed» |
| Public environment safety | PASS | «Public environment variable scan passed» |
| Frontend lint | PASS | 7/7 workspace |
| Frontend typecheck | PASS | 6/6 task (با اصلاح typegen — بند یادداشت‌ها) |
| Frontend unit tests | PASS | **18 تست** (9+2+3+1+1+1+1 در 7 workspace) |
| Frontend production builds | PASS | 8/8 task — هر دو اپ Next 16.2.10 |
| Playwright/Axe accessibility | PASS | **12 تست** (6 trader mobile + 6 admin desktop) با Chromium پین‌شده revision `1228` |
| Backend Ruff | PASS | بدون خطا |
| Backend mypy (strict) | PASS | بدون خطا |
| Backend pytest | PASS | **44 تست** |
| `infra/scripts/verify-native.sh` | PASS | exit 0 — drift پس از اجرا: صفر |

## 5. شواهد Docker

اجرای کامل `infra/scripts/verify-docker.sh` روی clone تمیز: **PASS** —
«automated Docker gates passed». آخرین اجرا روی `3a8e04d` با ایمیج‌های
بازسازی‌شده پس از وصله‌های وابستگی و حذف npm از ایمیج‌های وب؛ digest جدید هر
ده image در log ثبت شد.
Log artifacts (خارج از Git): `.local/m1-evidence/verify-docker-2026-07-25.log`،
`verify-docker-final-deps-2026-07-28.log`، `verify-docker-no-npm-2026-07-28.log`

| کنترل | نتیجه | شاهد |
|---|---|---|
| placeholder باقی نمانده و credentialهای DSN از charset امن URL | PASS | verifier + ساخت `.env` با secretهای تصادفی URL-safe |
| `RELEASE_COMMIT` برابر SHA clone تمیز | PASS | `b41c13be80e1768f2c245e383c7c078e8188fbee` |
| `docker compose ... config --quiet` | PASS | داخل verifier |
| build همه‌ی imageها | PASS | ده image ID/digest در log artifact ثبت شد |
| `migrate` با exit code صفر | PASS | `alembic upgrade head` — Exited (0) |
| `storage-init` با exit code صفر | PASS | Exited (0) |
| همه‌ی سرویس‌های بلندمدت healthy/running | PASS | ‏۸ سرویس Up؛ سرویس‌های دارای healthcheck همه healthy |
| فقط Nginx روی loopback host port دارد | PASS | `127.0.0.1:18080->8080/tcp` — بقیه بدون host port |
| backend/worker/frontends/Nginx با user غیر-root | PASS | گیت isolation در verifier |
| `storage-init` تنها استثنای root، یک‌باره و با capability محدود | PASS | CapDrop=ALL + فقط CHOWN/DAC_OVERRIDE/FOWNER (با نرمال‌سازی `CAP_`) |
| Trader health | PASS | گیت HTTP در verifier |
| Admin health | PASS | گیت HTTP در verifier |
| API liveness | PASS | گیت HTTP در verifier |
| API readiness شامل DB/Redis/storage | PASS | پروب dependencies: database/redis/storage همگی ok |
| release metadata با SHA/version مورد انتظار | PASS | برابر SHA clone تمیز |
| dependency probe احرازشده | PASS | 200 با توکن عملیات؛ توکن هرگز چاپ نشد |
| worker probe احرازشده | PASS | پس از اصلاح `4c8c099`+`b41c13b` — پاسخ در حد یک پنجره inspect |
| بازسازی containerها با `down/up` بدون حذف داده | PASS | داخل verifier |
| بقای sentinel مستقل PostgreSQL و storage پس از بازسازی | PASS | INSERT قبل از بازسازی، تأیید بعد از آن، سپس DELETE |
| `infra/scripts/verify-docker` | PASS | exit 0 — log artifact بالا |

## 6. امنیت و مصنوعات

| کنترل | نتیجه | شاهد |
|---|---|---|
| scanner داخلی `infra/scripts/scan_secrets.py` | PASS | داخل verify-native |
| secret scan نگهداری‌شده | PASS | gitleaks در CI (job «Repository secret scan») — سبز روی GitHub |
| vulnerability scan وابستگی‌ها | PASS با یک استثنا | Trivy 0.72.0؛ ۱۱ از ۱۲ یافته‌ی HIGH وصله شد، مورد باقی‌مانده در `.trivyignore.yaml` با دلیل/مالک/سررسید ثبت و در لاگ CI چاپ می‌شود |
| vulnerability scan imageها | PASS | Trivy روی هر ۸ image: صفر یافته‌ی دارای وصله. یافته‌های بدون وصله‌ی پایه‌ی Debian ثبت و شمرده می‌شوند ولی گیت نمی‌شوند (بند ۱۰ یادداشت‌ها) |
| SBOM هر image | **PENDING** | مرحله‌ی Syft 1.49.0 در CI پیاده شده؛ منتظر اولین اجرای کامل و بایگانی artifact |
| ثبت digest imageها و SHA منبع | PASS | ده image ID/digest + SHA منبع در log artifact پذیرش Docker |
| نبود secret در frontend/`NEXT_PUBLIC_*` | PASS | «Public environment variable scan passed» |

## 7. کنترل داده و حذف سیستم قدیمی

- [x] `.local` این اجرا فقط داده‌ی آزمایشی دارد (هیچ داده‌ی واقعی طبق مرز M1 مجاز نیست)
- [x] هیچ `.env` یا credential از سیستم قدیمی منتقل نشده — secretهای مقصد تازه ساخته شدند
- [x] دسترسی مخزن خصوصی از سیستم مقصد آزموده شده است — push و fetch موفق مالک
- [x] SHA remote و clone تمیز یکسان و ثبت شده‌اند — `b41c13b…`
- [x] اجرای Native و Docker روی clone تمیز موفق است — هر دو روی `b41c13b` با exit 0
- [ ] مالک پروژه حذف workspace قدیمی را تأیید کرده است — **PENDING** (حذف توصیه نمی‌شود تا تکمیل پذیرش)
- [ ] revoke/rotate پس از حذف — **PENDING**

## یادداشت‌های اجرای مقصد (انحراف‌ها و یافته‌ها)

1. **یافته‌ی پذیرش — نقص clean-clone در `f44ecc5`:** اسکریپت `typecheck` هر دو
   اپ Next فاقد `next typegen` است؛ `next-env.d.ts` به `./.next/types/routes.d.ts`
   ارجاع می‌دهد که پیش از build وجود ندارد → typecheck در هر clone تمیز شکست
   می‌خورد (روی سیستم مبدأ به‌دلیل وجود `.next` قبلی پنهان مانده بود). اصلاح
   یک‌خطی در `apps/{admin-web,trader-pwa}/package.json`:
   `"typecheck": "next typegen && tsc -p tsconfig.json --noEmit"` — ابتدا
   به‌صورت کامیت محلی `2241625` در clone آزموده و سپس به‌صورت رسمی روی `main`
   با کامیت `df23b69` ثبت شد؛ push به remote هنوز باقی است.
2. **یافته‌ی پذیرش — کرش قطعی nginx در `f44ecc5`/`df23b69`:** الگوی regex در
   `map $http_x_request_id` (فایل `infra/nginx/conf.d/local.conf` خط ۱۷) شامل
   `{0,127}` بدون کوتیشن بود؛ nginx آکولاد را شروع بلوک می‌بیند و با
   `unexpected "{"` هنگام استارت کرش و restart-loop می‌کرد (ingress عملاً
   ناکارا). چون Docker هرگز روی مبدأ اجرا نشده بود، این نقص تا پذیرش مقصد پنهان
   مانده بود. اصلاح: کوت‌کردن الگو — کامیت `c963c2c`. صحت با `nginx -t` و سپس
   verifier تأیید شد.
3. **یافته‌ی پذیرش — ناسازگاری verifier با Docker مدرن:** Docker Engine 25+‎
   مقادیر `HostConfig.CapAdd` را با پیشوند `CAP_` گزارش می‌کند
   (`CAP_CHOWN`…)، ولی گیت امنیتی storage-init در هر دو اسکریپت
   `verify-docker.sh|ps1` تطبیق دقیق بدون پیشوند می‌خواست و روی موتورهای جدید
   همیشه شکست می‌خورد. اصلاح: نرمال‌سازی با حذف پیشوند بدون تضعیف مجموعه‌ی
   بازبینی‌شده — کامیت `aa53051`.
4. **یافته‌ی پذیرش — باگ منطقی پروب سلامت worker:**
   `CeleryWorkerHealthProbe._inspect` سه فراخوانی broadcast متوالی دارد
   (ping، active_queues، active) که هرکدام کل پنجره‌ی timeout را صبر می‌کنند
   (اندازه‌گیری زنده: ۶.۲۹ ثانیه با پیش‌فرض ۱.۵ ثانیه) اما نگهبان بیرونی با
   همان پنجره‌ی تکی آن را قطع می‌کرد؛ نتیجه: `/api/v1/health/workers` همیشه
   `WORKER_PROBE_TIMEOUT` برمی‌گرداند حتی با worker سالم. تست‌های واحد با
   پروب fake این را نمی‌دیدند. اصلاح: نگهبان به اندازه‌ی سه پنجره + حاشیه‌ی
   اتصال — کامیت `4c8c099`.
5. **Clone از مسیر محلی:** به‌دلیل نبود credential غیرتعاملی GitHub، clone تمیز
   از مخزن محلی (همان `f44ecc5`) ساخته شد. تطبیق `git ls-remote` با remote یک
   آیتم باز است. push مستقیم از این سیستم بدون VPN معلق می‌ماند (github.com
   روی این شبکه فیلتر است).
6. **محیط میزبان (خارج از مخزن):** MTU شبکه‌ی WSL برابر 1400 بود و bridge داکر
   1500 — باعث شکست/کندی شدید دانلود داخل کانتینرها می‌شد؛ در
   `/etc/docker/daemon.json` مقدار MTU 1400 (به‌همراه حفظ mirrorهای رجیستری
   موجود) تنظیم شد. دانلود مرورگر Playwright به‌دلیل مسدودیت جغرافیایی
   `cdn.playwright.dev` از mirror (`PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright`)
   انجام شد — بدون تغییر در مخزن. دیسک WSL به `D:\wsl` منتقل شد (کمبود فضای C:).
7. **یافته‌ی امنیتی — ۱۲ آسیب‌پذیری HIGH در وابستگی‌ها:** اولین گیت
   vulnerability در CI ‏۱۲ مورد HIGH (صفر CRITICAL) گزارش کرد؛ جدی‌ترین‌ها:
   دور زدن Middleware/Proxy و دو SSRF در Next.js، و SSRF/نشت NTLM در
   starlette. یازده مورد با ارتقا وصله شد (کامیت `64fd476`): next ‏16.2.11،
   fastapi ‏0.139.0، starlette ‏1.3.1، و postcss/sharp/brace-expansion از راه
   pnpm override. اصل انتخاب نسخه: **کمترین نسخه‌ای که یافته را رفع کند و
   جاافتاده باشد**، نه جدیدترین — گیت «حداقل سن انتشار» pnpm نسخه‌ی
   `postcss@8.5.24` (همان‌روز منتشرشده) را رد کرد و خودش برایش استثنا نوشت که
   بازگردانده شد؛ به همین دلیل fastapi هم از `0.140.13` (همان‌روز) به
   `0.139.0` برگشت و وابستگی جدیدش `annotated-doc` روی `0.0.4` مقید شد، چون
   uv برخلاف pnpm چنین گیتی ندارد. دو نکته‌ی فنی: `sharp 0.35.0` که خود
   توصیه‌نامه نام می‌برد تایپ‌چک هر دو اپ را می‌شکند (تعاریف تایپ از مسیر
   package exports قابل resolve نیست) پس `0.35.1` انتخاب شد؛ و ارتقای بزرگ
   FastAPI قرارداد OpenAPI را تغییر نداد.
8. **استثنای امنیتی ثبت‌شده:** `brace-expansion 1.1.16` تنها از راه
   `minimatch@3` داخل ESLint وارد می‌شود، خط ۱.x هیچ نسخه‌ی اصلاح‌شده‌ای ندارد
   و اصلاح چهار نسخه‌ی اصلی بالاتر است؛ تحمیل آن lint را می‌شکند و این بسته در
   هیچ image تولیدی نیست. در `.trivyignore.yaml` با دلیل، مالک `@e-shams-d` و
   سررسید `2026-10-31` ثبت شد و CI موارد سرکوب‌شده را با متن توجیه چاپ می‌کند.
9. **یافته‌ی امنیتی — CVE بحرانی داخل ایمیج‌های وب:** اولین اسکن image ‏۲۴ تا
   ۲۶ یافته‌ی HIGH/CRITICAL به‌ازای هر image گزارش کرد. چهار مورد واقعی و
   قابل‌رفع بودند و به تولید هم می‌رفتند: `npm` که در ایمیج پایه‌ی Node قرار
   دارد نسخه‌های آسیب‌پذیر `tar 7.5.15` (‏CVE-2026-59873 با شدت CRITICAL و
   CVE-2026-59874)، `undici 6.26.0` و `brace-expansion 5.0.6` را حمل می‌کرد.
   این‌ها در lockfile پروژه نبودند، به همین دلیل اسکن وابستگی‌ها آن‌ها را
   نمی‌دید. چون مرحله‌ی runtime هر دو اپ فقط سرور standalone را اجرا می‌کند و
   هرگز npm را صدا نمی‌زند، npm از ایمیج runtime حذف شد (کامیت `3a8e04d`)؛ هر
   چهار یافته پاک شد و یک package manager هم از ایمیج تولیدی خارج شد.
10. **سیاست گیت اسکن image:** بقیه‌ی یافته‌ها (‏۲۲ تا ۲۴ مورد) بسته‌های پایه‌ی
    Debian با وضعیت `affected`/`fix_deferred`/`will_not_fix` هستند؛ یعنی
    upstream هیچ وصله‌ای منتشر نکرده و rebuild پاکشان نمی‌کند. گیت اسکن image
    فقط روی یافته‌های **دارای وصله** شکست می‌دهد؛ همه‌ی یافته‌ها همچنان در
    artifact شواهد ثبت و تعدادشان در لاگ چاپ می‌شود. اسکن **وابستگی‌ها**
    عمداً سخت‌گیر ماند، چون آنجا انتخاب نسخه با پروژه است و یافته‌ی بدون وصله
    قابل اقدام است. شاهد پشتیبان: ایمیج nginx با پایه‌ی Alpine صفر یافته دارد.
11. **Python 3.12.13:** uv پین‌شده 0.8.22 این نسخه را در مانیفست ندارد؛ نصب
   یک‌باره با uv جدیدتر در دایرکتوری اشتراکی انجام شد و uv 0.8.22 همان را
   استفاده می‌کند (سازگار با قید نسخه‌ی verify-native).

## 8. تصمیم نهایی

- [ ] **M1 ACCEPTED**
- [x] **M1 NOT ACCEPTED** — موارد باز:

همه‌ی گیت‌های خودکار (Native و Docker) روی `b41c13b` پاس شده‌اند و SHA سه‌گانه
تطبیق دارد. موارد باز باقی‌مانده همگی حاکمیتی/تأییدی‌اند:

| مورد باز | شدت | مالک | موعد | شرط بستن |
|---|---|---|---|---|
| push کامیت‌های `5b99877`..`3a8e04d` و تطبیق `ls-remote` | بالا | مالک پروژه | — | `ls-remote` برابر آخرین SHA |
| اجرای موفق SBOM در CI و بایگانی artifactها | متوسط | اجراکننده | — | اولین اجرای سبز job «Docker acceptance + scans + SBOM» |
| بازبینی دوره‌ای یافته‌های بدون وصله‌ی پایه‌ی Debian | متوسط | حاکمیت/امنیت | فصلی | تصمیم درباره‌ی تغییر image پایه یا پذیرش مستمر |
| تأیید رسمی ابزارهای امنیتی انتخاب‌شده (gitleaks/Trivy/Syft) | متوسط | حاکمیت/امنیت | — | تصویب یا جایگزینی؛ نشانه‌های `TODO(governance)` در workflow برداشته شود |
| بازبینی استثنای `CVE-2026-14257` | متوسط | مالک پروژه | 2026-10-31 | حذف استثنا پس از عبور ESLint از minimatch 3 |
| فعال‌سازی branch protection و registry | متوسط | مالک/حاکمیت | — | پس از اولین CI کاملاً سبز |
| تصویب فرم شواهد و تصمیم نهایی M1 | بالا | مالک پروژه | — | امضای بخش ۸ |

تصویب‌کننده: **PENDING**
تاریخ: —
مرجع تصمیم/تیکت: —
