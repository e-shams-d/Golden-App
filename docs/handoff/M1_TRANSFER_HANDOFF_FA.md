# راهنمای تحویل و ادامه‌ی M1 روی سیستم مقصد

Status: **M1 CANDIDATE / NOT ACCEPTED**
Snapshot date: 2026-07-23
Scope: انتقال امن کد و مستندات از طریق مخزن خصوصی و تکمیل پذیرش M1 روی سیستم
دارای Docker

## 1. معنی وضعیت فعلی

پیاده‌سازی پایه‌ی M1 برای انتقال آماده می‌شود، اما M1 هنوز پذیرفته‌شده نیست.
عبارت Candidate یعنی کد، lockfileها، پوسته‌های اجرایی، تست‌های Native و زیرساخت
Compose وجود دارند؛ عبارت Not Accepted یعنی هنوز این موارد روی یک clone تمیز
از commit نهایی و با Docker واقعی اثبات نشده‌اند.

این سند مجوز استفاده‌ی عملیاتی یا شروع منطق مالی نیست. تا وقتی فرم
`M1_ACCEPTANCE_EVIDENCE_TEMPLATE_FA.md` کامل و تصویب نشده است، وضعیت M1 باید
همان **Candidate / Not Accepted** بماند.

## 2. عکس وضعیت مبدأ

در زمان تهیه‌ی این راهنما:

- شاخه‌ی محلی `master` است، اما نام شاخه‌ی پیش‌فرض هنوز یک تصمیم حاکمیتی باز
  است.
- base commit پیش از بسته‌بندی نهایی
  `22ee5363ff3a87408185bc4ccc7f3c43849b5d01` است.
- هیچ remote برای Git تنظیم نشده است.
- tree آماده‌ی انتقال پیش از commit شامل ۲۳۸ فایل Git-visible است: ۲۹ فایل
  موجود در base و ۲۰۹ فایل جدید. بنابراین base commit بالا **commit انتقال
  نیست** و شمار نهایی پس از commit باید با `git ls-tree -r --name-only HEAD`
  دوباره کنترل شود.
- فایل `.env` وجود ندارد و نباید هم commit شود.
- Docker روی سیستم مبدأ در دسترس نیست؛ در نتیجه Compose، image build، migration
  و سلامت stack در این سیستم پذیرفته نشده‌اند.
- adapter مربوط به ارائه‌دهنده‌ی CI، `CODEOWNERS` واقعی و branch protection به
  دلیل نامشخص بودن ارائه‌دهنده، نام تیم‌ها و remote هنوز قابل نهایی‌سازی نیستند.

قبل از push باید همه‌ی فایل‌های موردنظر بازبینی، secret-scan، stage و در یک
commit نهایی ثبت شوند. مقدار `TRANSFER_SHA` فقط بعد از همان commit ساخته می‌شود
و جای base commit بالا را در شواهد تحویل می‌گیرد.

## 3. چه چیزهایی پیاده‌سازی شده است

### ساختار و runtime

- monorepo با دو برنامه‌ی مستقل `apps/trader-pwa` و `apps/admin-web`
- backend ماژولار FastAPI در `services/backend`
- پنج package اشتراکی در `packages`: API client، auth client، UI، localization
  و config
- PostgreSQL 16 به‌عنوان مرجع durable و Redis/Celery صرفاً به‌عنوان
  broker/support غیرمرجع
- Alembic baseline با head برابر `20260720_0001`
- health، readiness، dependency و worker probes با خروجی allow-listed
- storage interface و local private-storage adapter برای توسعه/pilot
- Nginx به‌عنوان تنها ingress محلی روی loopback؛ DB، Redis، backend و frontend
  مستقیماً روی host منتشر نمی‌شوند
- Dockerfileهای backend، دو frontend و Nginx و Compose topology شامل
  `nginx`، `trader-pwa`، `admin-web`، `backend`، `worker`، `scheduler`,
  `migrate`، `storage-init`، `postgres` و `redis`

### تکرارپذیری و قرارداد

- Node.js `24.18.0` در `.nvmrc`
- pnpm `11.15.1` و lockfile ریشه
- Python `3.12.13` در `.python-version`
- uv `0.8.22` و `services/backend/uv.lock`
- PostgreSQL image `16.14-alpine3.24`
- Redis image `7.4.9-alpine3.21`
- OpenAPI سروری به‌عنوان منبع حقیقت با artifact قطعی در
  `services/backend/openapi/v1.json`
- typeهای تولیدشده‌ی frontend در
  `packages/api-client/src/generated/openapi.d.ts`
- فرمان‌های ریشه‌ی `pnpm openapi:generate` برای تولید و
  `pnpm openapi:check` برای تشخیص drift
- اسکریپت‌های provider-neutral در
  `infra/scripts/verify-native.ps1|sh` و
  `infra/scripts/verify-docker.ps1|sh`؛ wrapperهای `verify.ps1|sh` هر دو بخش را
  اجرا می‌کنند

این workflow یک candidate فنی برای routeهای غیرمالی M1 است؛ به معنی تصویب
راهبرد OpenAPI، freeze قراردادهای مالی یا رفع gate حاکمیتی OpenAPI نیست.

### ایمنی پایه

- قرارداد پول: عدد صحیح IRR؛ Toman فقط نمایش/ورودی با provenance روشن
- ذخیره و انتقال زمان: UTC/Gregorian؛ timezone کسب‌وکار `Asia/Tehran`
- root filesystem سرویس‌های application تا حد امکان read-only، حذف capability
  و `no-new-privileges`
- credentialهای نمونه فقط placeholder هستند و `.env`، کلیدها، cacheها و داده‌ی
  محلی با `.gitignore` خارج شده‌اند
- `OPERATIONS_HEALTH_TOKEN` با placeholder حداقل ۳۲ کاراکتری در template ریشه
  وجود دارد و Compose آن را به backend، worker و scheduler می‌دهد؛ مقدار واقعی
  فقط باید در `.env` مقصد باشد
- `NEXT_PUBLIC_*` فقط برای تنظیم عمومی routing است و نباید secret داشته باشد
- persistence محلی با `down` حفظ می‌شود؛ استفاده از `down -v` بدون قصد صریح
  حذف داده ممنوع است

## 4. شواهد موجود و محدودیت آن‌ها

آخرین اجرای Native روی workspace مبدأ این نتایج را گزارش کرده است:

- ۴۱ تست backend موفق
- Ruff و mypy موفق
- Alembic دارای head مورد انتظار
- ۱۳ تست واحد frontend/package موفق
- lint، typecheck و build frontend موفق
- ۱۲ تست Playwright/Axe موفق؛ این smoke محلی با Chromium cache موجود revision
  `1208` اجرا شد، در حالی که Playwright قفل‌شده revision `1228` را می‌خواهد
- اعتبارسنجی ساختاری مخزن و یکپارچگی manifest مستندات M0 موفق

این اعداد فقط شاهد توسعه روی سیستم مبدأ هستند. چون فایل‌ها در آن زمان هنوز در
commit انتقال نبودند و Docker موجود نبود، این شواهد به‌تنهایی پذیرش M1 نیستند.
همچنین Python محلی این اجرا `3.12.10` بود، نه patch دقیق `3.12.13` ثبت‌شده در
مخزن. همه‌ی کنترل‌ها باید از clone تمیز SHA نهایی روی سیستم مقصد، با Python
`3.12.13` و Chromium revision `1228` دوباره تولید شوند.

## 5. چه چیزهایی نباید با کپی دستی یا Git منتقل شوند

کد، مستندات، lockfileها، migrationها، Dockerfileها، Compose و templateهای
`.env.example` باید از مخزن خصوصی بیایند. موارد زیر نباید commit یا داخل archive
مخزن شوند:

- `.env` و هر `.env.*` واقعی به‌جز templateهای صریح `.env.example`
- password، token، API key، cookie/session، certificate و private key
- `.git` از کپی قدیمی؛ سیستم مقصد باید clone تازه بسازد
- `.local/` شامل PostgreSQL و storage محلی
- `.pnpm-store/`، `node_modules/`، `.venv/` و `venv/`
- `.next/`، `.turbo/`، `dist/`، `build/` و cacheهای Python/Node
- logها، coverage، Playwright report، `test-results` و فایل‌های موقت
- browser binaryهای دانلودشده‌ی Playwright

اگر `.local/postgres` یا `.local/storage` داده‌ی واقعاً لازم دارد، آن داده
artifact مخزن نیست. قبل از حذف سیستم قدیمی باید backup مستقل، رمزگذاری‌شده و
حداقل یک restore آزمایشی برای آن انجام شود. طبق مرز M1 داده‌ی واقعی معامله‌گر،
بانک یا پرداخت اصولاً نباید در این محیط وجود داشته باشد.

کپی zip یا mirror کل workspace روش تحویل قابل قبول نیست؛ ممکن است secret،
cache، داده‌ی محلی یا objectهای نامرتبط Git را منتقل کند.

## 6. آماده‌سازی و push به مخزن خصوصی

ارائه‌دهنده‌ی مخزن، URL، default branch، حساب‌های CODEOWNER و سیاست محافظت شاخه
هنوز مشخص نشده‌اند. ابتدا یک مخزن **private** ایجاد کنید و احراز هویت را با SSH
agent یا credential manager انجام دهید. token یا password را در URL، فایل
مستندات، shell history یا Git config ذخیره نکنید.

در سیستم مبدأ، پیش از commit:

```powershell
git status --short --untracked-files=all
git diff --check
python infra/scripts/validate_repository.py
python infra/scripts/scan_secrets.py
pnpm openapi:check
```

scanner داخلی یک کنترل high-confidence و بدون dependency است، اما جای scanner
نگهداری‌شده‌ی مورد تأیید تیم امنیت را نمی‌گیرد. آن scanner را نیز روی تاریخچه و
تمام tracked و untrackedهای قابل commit اجرا کنید. پس از تأیید فهرست فایل‌ها:

```powershell
git add --all
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
git commit -m "feat: prepare M1 foundation for transfer"
git rev-parse HEAD
```

خروجی ۴۰ کاراکتری آخر، `TRANSFER_SHA` است. در صورت نبود remote:

```powershell
git remote add origin <PRIVATE_REMOTE_URL>
git remote -v
git push -u origin HEAD:<TRANSFER_BRANCH>
git ls-remote origin refs/heads/<TRANSFER_BRANCH>
```

اگر `origin` از قبل وجود داشت، بدون بررسی آن را overwrite نکنید:

```powershell
git remote get-url origin
git remote set-url origin <PRIVATE_REMOTE_URL>
```

تغییر URL فقط وقتی مجاز است که remote فعلی بررسی و اشتباه بودنش قطعی شده باشد.
SHA خروجی `ls-remote` باید دقیقاً برابر `TRANSFER_SHA` باشد. صرف پیام
`Everything up-to-date` اثبات کافی نیست.

پس از تعیین provider، این کنترل‌ها نیز باید در همان سامانه فعال شوند:

- adapter CI که قرارداد `infra/ci/README.md` را بدون skip اجرا کند
- `CODEOWNERS` با هویت واقعی تیم‌ها
- protected default branch و الزام review
- الزام موفقیت Native، OpenAPI، Docker build، scan و artifact evidence
- ممنوعیت force-push و حذف شاخه‌ی محافظت‌شده طبق release policy مصوب
- registry خصوصی و promotion با digest همان image آزموده‌شده

## 7. پیش‌نیازهای دقیق سیستم مقصد

نسخه‌های pinشده:

| ابزار | نسخه/قید |
|---|---|
| Node.js | `24.18.0` |
| pnpm | `11.15.1` |
| Python | `3.12.13` |
| uv | `0.8.22` |
| PostgreSQL container | `16.14-alpine3.24` |
| Redis container | `7.4.9-alpine3.21` |

همچنین لازم است:

- Git و دسترسی احرازشده‌ی read/write به مخزن خصوصی
- Docker Engine فعال با Compose v2
- روی Windows، Docker Desktop با backend سالم WSL2 یا معادل مورد تأیید تیم
- روی Linux، دسترسی کاربر به Docker بدون قرار دادن credential در مخزن
- دسترسی شبکه به registryهای dependency و container مورد استفاده
- فضای آزاد کافی برای node modules، Python environment، Playwright Chromium و
  imageهای Docker

نسخه‌ی دقیق Docker، سیستم‌عامل production و معماری CPU هنوز تصمیم حاکمیتی باز
هستند؛ مقدار واقعی مقصد را در فرم شواهد ثبت کنید و سازگاری imageها را اثبات
کنید.

## 8. clone تمیز و bootstrap در Windows

از یک مسیر خالی و مستقل استفاده کنید:

```powershell
git clone <PRIVATE_REMOTE_URL> gold-platform-clean
Set-Location gold-platform-clean
git fetch --prune origin
git checkout --detach <TRANSFER_SHA>
git rev-parse HEAD
git status --porcelain
git fsck --full
```

`git rev-parse HEAD` باید با SHA ثبت‌شده‌ی remote برابر و خروجی
`git status --porcelain` خالی باشد.

حالت detached در این مرحله عمدی است تا پذیرش دقیقاً روی همان SHA انجام شود.
تا پایان پذیرش روی detached HEAD توسعه ندهید. پس از پذیرش و ثبت شواهد، شاخه‌ی
ادامه‌ی کار را از همان commit بسازید و push کنید:

```powershell
git switch -c <WORK_BRANCH> <TRANSFER_SHA>
git push -u origin <WORK_BRANCH>
```

نسخه‌ها و dependencyها:

```powershell
node --version
corepack enable
corepack prepare pnpm@11.15.1 --activate
pnpm --version
python --version
uv --version
docker version
docker compose version
pnpm install --frozen-lockfile
uv sync --project services/backend --frozen --group dev
pnpm --filter @gold/trader-pwa exec playwright install chromium
```

تنظیم local-only:

```powershell
Copy-Item .env.example .env
```

فایل `.env` را فقط روی سیستم مقصد و با secretهای جدید و محلی ویرایش کنید. تمام
مقادیر `change-me` باید عوض شوند. passwordهای PostgreSQL/Redis را با حداقل ۱۶
کاراکتر URL-safe از مجموعه‌ی `A-Z a-z 0-9 . _ ~ -` و
`OPERATIONS_HEALTH_TOKEN` را با حداقل ۳۲ کاراکتر از همین مجموعه بسازید؛ چون
passwordها داخل DSN قرار می‌گیرند، کاراکترهایی مانند `@ : / # % $` بدون encoding
امن مجاز نیستند. secret سیستم قدیمی را کپی نکنید. سپس بررسی کنید که فایل ignore
است:

برای traceability اجرای پذیرش، مقدار عمومی `RELEASE_COMMIT` را نیز برابر
`TRANSFER_SHA` بگذارید؛ این مقدار secret نیست و باید در `/api/v1/meta/release`
دیده شود.

```powershell
git check-ignore -v .env
git status --porcelain
```

## 9. clone تمیز و bootstrap در Linux

```bash
git clone <PRIVATE_REMOTE_URL> gold-platform-clean
cd gold-platform-clean
git fetch --prune origin
git checkout --detach <TRANSFER_SHA>
git rev-parse HEAD
git status --porcelain
git fsck --full
```

در Linux نیز تا پایان پذیرش روی detached HEAD توسعه ندهید. پس از قبولی، همان
دستورهای `git switch -c <WORK_BRANCH> <TRANSFER_SHA>` و
`git push -u origin <WORK_BRANCH>` را اجرا کنید.

نسخه‌ها و dependencyها:

```bash
node --version
corepack enable
corepack prepare pnpm@11.15.1 --activate
pnpm --version
python --version
uv --version
docker version
docker compose version
pnpm install --frozen-lockfile
uv sync --project services/backend --frozen --group dev
pnpm --filter @gold/trader-pwa exec playwright install --with-deps chromium
```

تنظیم local-only:

```bash
cp .env.example .env
git check-ignore -v .env
git status --porcelain
```

قبل از ادامه تمام `change-me`ها، از جمله `OPERATIONS_HEALTH_TOKEN` حداقل
۳۲ کاراکتری، را با secretهای تازه و مختص مقصد عوض کنید. passwordهای
PostgreSQL/Redis باید حداقل ۱۶ کاراکتر و همه‌ی این credentialها فقط از مجموعه‌ی
URL-safe برابر `A-Z a-z 0-9 . _ ~ -` باشند. مقدار `RELEASE_COMMIT` را هم دقیقاً
برابر `TRANSFER_SHA` قرار دهید.

## 10. پذیرش Native روی clone تمیز

در Windows:

```powershell
pnpm openapi:check
.\infra\scripts\verify-native.ps1
```

در Linux:

```bash
pnpm openapi:check
./infra/scripts/verify-native.sh
```

اگر permission اجرایی shell script در Git حفظ نشده بود، آن را با یک commit
اصلاح کنید؛ اجرای محلی با `sh infra/scripts/verify-native.sh` جای اصلاح mode
فایل در مخزن را نمی‌گیرد.

پس از اجرای موفق:

```bash
git status --porcelain
```

باید خالی بماند. تغییر `pnpm-lock.yaml`، `uv.lock`، OpenAPI JSON یا generated
TypeScript هنگام validation نشانه‌ی drift و رد پذیرش است. برای تغییر عمدی
قرارداد از `pnpm openapi:generate` استفاده، diff را review و در commit جدا ثبت
کنید؛ `openapi:check` نباید artifact را بی‌صدا بازنویسی کند.

## 11. پذیرش Docker روی clone تمیز

روش اصلی پذیرش، verifier رسمی است. در Windows:

```powershell
.\infra\scripts\verify-docker.ps1
```

و در Linux:

```bash
./infra/scripts/verify-docker.sh
```

verifier از project اختصاصی `gold-platform-m1-verify`، port پیش‌فرض `18080` و
data root جداگانه‌ی `.local/m1-verify/<PROJECT_NAME>` استفاده می‌کند؛ بنابراین stack معمول
`gold-platform-local` را متوقف نمی‌کند. اگر containerی از project پذیرش از قبل
وجود داشته باشد، verifier به‌جای تصاحب یا پایین‌آوردن آن متوقف می‌شود. نام project
و port فقط در صورت نیاز با `M1_VERIFY_PROJECT_NAME` و `M1_VERIFY_HTTP_PORT` قابل
تغییرند.

شرایط مورد انتظار:

- `migrate` و `storage-init` با exit code صفر تمام شوند.
- `nginx`، `trader-pwa`، `admin-web`، `backend`، `worker`، `scheduler`,
  `postgres` و `redis` running باشند.
- سرویس‌های دارای healthcheck به حالت healthy برسند.
- فقط Nginx روی loopback و port اختصاصی verifier منتشر شود.
- PostgreSQL، Redis، backend، worker و frontendها host port نداشته باشند.
- backend، worker، scheduler، migrate، هر دو frontend و Nginx با user غیر-root
  اجرا شوند.
- `storage-init` تنها استثنای root است، باید یک‌باره با exit code صفر تمام شده
  و فقط capabilityهای محدود تعریف‌شده در Compose را داشته باشد.
- مقدار public `RELEASE_COMMIT` در پاسخ release metadata دقیقاً با SHA clone
  تمیز برابر باشد.
- sentinel غیرمالی PostgreSQL و storage پس از `down/up` بدون حذف داده باقی بماند
  و سپس پاک شود.

verifier تمام endpointهای عمومی، probeهای restricted، release metadata و health
واقعی containerهای دارای healthcheck را کنترل می‌کند. token فقط از environment
داخل backend خوانده می‌شود و در command line یا خروجی چاپ نمی‌شود. سپس یک
sentinel غیرمالی مستقل در PostgreSQL و storage می‌نویسد، containerها را با
`down/up` و بدون حذف داده بازسازی می‌کند، بقای هر دو sentinel را می‌سنجد و
sentinelها را پاک می‌کند. image ID و digestهای موجود نیز بدون اطلاعات محرمانه
در خروجی ثبت می‌شوند.

در پایان، verifier project خودش را با `down` و بدون `--volumes` متوقف می‌کند.
data آزمایشی زیر `.local/m1-verify/<PROJECT_NAME>` عمداً خودکار حذف نمی‌شود.
`down -v` یا حذف
recursive داده جزو acceptance نیست و نباید بدون تصمیم صریح اجرا شود.

اگر cleanup شکست خورد، containerهای project اختصاصی را بدون دست‌کاری stack
معمول با این فرمان پیدا کنید:

```bash
docker ps -a --filter label=com.docker.compose.project=gold-platform-m1-verify
```

فقط status، image ID/digest و فیلدهای allow-listed را در evidence نگه دارید.
هر log را پیش از نگهداری یا ارسال از نظر secret و داده‌ی حساس پاک‌سازی کنید.

پیام موفقیت verifier فقط به معنی عبور gateهای خودکار Docker است؛ پذیرش کامل M1
همچنان به scan نگهداری‌شده، SBOM، شواهد CI، تطبیق remote/clone و تصویب مالک نیاز
دارد.

## 12. شواهد امنیت و supply chain

پذیرش M1 علاوه بر build نیازمند موارد زیر است:

- secret scan روی تاریخچه و tree نهایی
- vulnerability scan وابستگی‌های Python و Node
- vulnerability scan همه‌ی imageهای ساخته‌شده
- SBOM برای هر image
- ثبت image ID/digest، `TRANSFER_SHA`، نسخه ابزار و زمان اجرا
- ثبت و تعیین تکلیف هر یافته‌ی High/Critical

ابزار دقیق scan/SBOM و registry هنوز در حاکمیت انتخاب نشده است. نبود ابزار
انتخاب‌شده مجوز skip نیست؛ این gate باید با مالک، ابزار و شاهد تکمیل شود.
imageهای production باید با digest آزموده‌شده promote شوند و نباید از branch
متحرک دوباره build شوند.

## 13. موارد باقی‌مانده برای اتمام M1

### انتقال و کنترل منبع

- [ ] تعیین provider، URL مخزن private و نام شاخه‌ی تحویل
- [ ] secret scan همه‌ی فایل‌های نهایی
- [ ] commit کردن تمام فایل‌های موردنظر و ثبت `TRANSFER_SHA`
- [ ] push موفق و تطبیق SHA با `git ls-remote`
- [ ] clone تمیز روی سیستم مقصد و اثبات clean status

### CI و حاکمیت تحویل

- [ ] انتخاب و پیاده‌سازی adapter CI
- [ ] مقایسه‌ی pin‌شده‌ی OpenAPI با merge-base شاخه‌ی محافظت‌شده و رد تغییر
  breaking بدون bump نسخه یا waiver مصوب
- [ ] پیش از اضافه‌شدن API مالی، تصمیم درباره‌ی جایگزینی generator داخلی با ابزار
  نگهداری‌شده یا تکمیل fixtureهای قرارداد برای همه‌ی constructهای مجاز
- [ ] تعیین `CODEOWNERS` با تیم/کاربر واقعی
- [ ] تصویب default branch، review و release policy
- [ ] protected branch و required checks
- [ ] انتخاب registry، scan/SBOM tooling و retention شواهد

### پذیرش فنی مقصد

- [ ] نصب frozen dependencyها بدون drift
- [ ] `openapi:check` و تمام کنترل‌های Native
- [ ] ثبت تصمیم فنی OpenAPI؛ workflow موجود نباید به‌عنوان freeze قرارداد مالی
  تلقی شود
- [ ] Compose render و build
- [ ] اجرای موفق `migrate` و `storage-init`
- [ ] health/readiness همه‌ی سرویس‌ها و endpointها
- [ ] dependency/worker probe احرازشده بدون افشای operations token
- [ ] restart و persistence smoke
- [ ] scan مخزن/image و تولید SBOM
- [ ] تکمیل و تصویب فرم شواهد

تا باز بودن هر مورد اجباری، برچسب M1 همان Candidate / Not Accepted است.

## 14. مرزهای ایمنی M0 برای ادامه‌ی پیاده‌سازی

M0 کامل نیست: ۹ مورد از ۲۴ gate ثبت‌شده بسته و ۱۵ مورد باز است. register شامل
۳۳ conflict است که ۲۶ مورد باز و ۵ مورد Critical هستند. پنج Critical باز:

1. نام‌ها و stateهای canonical برای `PaymentRequest`
2. اختیار اصلاح نتیجه‌ی پرداخت‌شده‌ی منتشرشده
3. نگاشت namespace/aliasهای ADR
4. تصویب صریح baseline محصول و دامنه
5. شناسه‌های canonical permission

بنابراین بعد از انتقال می‌توان foundationهای برگشت‌پذیر M1، tooling،
observability، shellهای UI، adapterهای بدون منطق مالی و تست زیرساخت را ادامه
داد؛ اما این کارها تا تصویب قرارداد مربوطه ممنوع‌اند:

- migration، enum یا table مالی
- command/API مالی و generated client وابسته به catalogue تصویب‌نشده
- workflow واقعی معامله، batch، بانک، پرداخت، matching یا اصلاح نتیجه
- authorization مالی بر پایه‌ی permissionهای freezeنشده
- UI مالی که state/permission حل‌نشده را به قرارداد عملی تبدیل کند
- استفاده از داده‌ی واقعی معامله‌گر، فایل بانکی، پرداخت یا credential production

AI/OCR، bank API، Android/Windows packaging، chat و multi-company نیز خارج از
scope/غیرفعال می‌مانند. هیچ تصمیم باز نباید با یک default پنهان در کد مالی
تثبیت شود.

## 15. چک‌لیست حذف امن سیستم قدیمی

حذف workspace قدیمی فقط وقتی مجاز است که همه‌ی موارد زیر تیک خورده باشند:

- [ ] تمام فایل‌های لازم در commit نهایی‌اند و `git status` مبدأ بررسی شده است.
- [ ] secret scan پیش از push موفق است.
- [ ] commit نهایی به remote private push شده است.
- [ ] SHA شاخه در remote دقیقاً برابر `TRANSFER_SHA` است.
- [ ] همان SHA در یک مسیر خالی روی سیستم مقصد clone شده است.
- [ ] clean clone فاقد تغییر و شامل کد، مستندات، هر دو lockfile، OpenAPI JSON،
  generated TypeScript، migrationها و زیرساخت است.
- [ ] Native verification روی clean clone موفق است.
- [ ] Docker verification، migration، health، restart و persistence موفق‌اند.
- [ ] شواهد scan، SBOM و image digest ثبت شده‌اند.
- [ ] هر داده‌ی محلی لازم backup و restore آزمایشی شده یا حذف‌پذیر بودن آن
  صریحاً تأیید شده است.
- [ ] دسترسی مخزن از مقصد مستقل از credential سیستم قدیمی کار می‌کند.
- [ ] مالک پروژه فرم پذیرش را امضا و حذف را صریحاً تأیید کرده است.

تا قبل از تکمیل این فهرست، workspace مبدأ را حذف، move یا پاک‌سازی recursive
نکنید.

پس از تأیید:

1. برنامه‌ها و containerهای محلی را بدون `-v` متوقف کنید، مگر حذف volume
   صریحاً تصویب شده باشد.
2. اگر backup لازم است، صحت و قابلیت restore آن را دوباره بررسی کنید.
3. workspace را با ابزار مدیریت فایل سیستم‌عامل حذف کنید؛ حذف را از داخل
   اسکریپت repository خودکار نکنید.
4. credentialها، tokenها و sessionهای مختص سیستم قدیمی را revoke/rotate کنید.
5. در صورت واگذاری یا دورریزی دستگاه، از روش پاک‌سازی امن مورد تأیید سازمان
   استفاده کنید.
6. نتیجه‌ی حذف و وضعیت recoverability را در تیکت انتقال ثبت کنید.

این ترتیب مانع از وضعیتی می‌شود که تنها کپی کد یا مستندات قبل از اثبات remote و
سیستم مقصد از بین برود.
