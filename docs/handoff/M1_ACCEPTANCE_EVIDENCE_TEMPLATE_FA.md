# فرم شواهد انتقال و پذیرش M1

Status: EMPTY TEMPLATE — NOT ACCEPTED
Milestone: M1 — Repository and Runtime Foundation

این فرم را روی سیستم مقصد تکمیل و در محل کنترل‌شده‌ی شواهد پروژه نگهداری کنید.
اگر سیاست پروژه نگهداری داخل Git را الزام می‌کند، فرم تکمیل‌شده باید در یک commit
بعدیِ evidence-only قرار گیرد و به `TRANSFER_SHA` قبلی اشاره کند؛ خود commit انتقال
نمی‌تواند SHA خودش را در محتوای خود ثبت کند. اطلاعات محرمانه، token، password،
محتوای `.env`، کلید خصوصی، آدرس داخلی حساس یا log دارای داده‌ی محرمانه نباید در
این فایل ثبت شود.

## 1. هویت تحویل

| مورد | مقدار |
|---|---|
| تاریخ و ساعت با timezone | `<YYYY-MM-DD HH:mm ZONE>` |
| نام مخزن خصوصی | `<REPOSITORY_NAME>` |
| ارائه‌دهنده‌ی مخزن | `<GitHub/GitLab/Bitbucket/Azure DevOps/Other>` |
| نام remote | `origin` |
| شاخه‌ی تحویل | `<TRANSFER_BRANCH>` |
| SHA مورد انتظار | `<TRANSFER_SHA_40_HEX>` |
| SHA دریافت‌شده از remote | `<REMOTE_SHA_40_HEX>` |
| SHA در clone تمیز | `<CLEAN_CLONE_SHA_40_HEX>` |
| سیستم‌عامل و معماری مقصد | `<OS_VERSION / CPU_ARCH>` |
| اجراکننده | `<NAME_OR_ACCOUNT>` |
| بازبین | `<NAME_OR_ACCOUNT>` |

شرط قبولی این بخش:

- [ ] سه مقدار SHA بالا دقیقاً یکسان‌اند.
- [ ] commit از remote مخزن خصوصی قابل دریافت است.
- [ ] clone در یک مسیر خالی و مستقل از هر کپی دستی انجام شده است.
- [ ] خروجی `git status --porcelain` در clone تمیز خالی است.
- [ ] فایل‌های `pnpm-lock.yaml`، `services/backend/uv.lock`،
  `services/backend/openapi/v1.json` و
  `packages/api-client/src/generated/openapi.d.ts` در همان commit وجود دارند.

## 2. نسخه‌ی ابزارها

خروجی‌ها را بدون اطلاعات حساس ثبت کنید.

| فرمان | مقدار مورد انتظار | مقدار مشاهده‌شده | نتیجه |
|---|---|---|---|
| `git --version` | نسخه‌ی پشتیبانی‌شده | `<...>` | `<PASS/FAIL>` |
| `node --version` | `v24.18.0` | `<...>` | `<PASS/FAIL>` |
| `pnpm --version` | `11.15.1` | `<...>` | `<PASS/FAIL>` |
| `python --version` | `3.12.13` | `<...>` | `<PASS/FAIL>` |
| `uv --version` | `0.8.22` | `<...>` | `<PASS/FAIL>` |
| `docker version` | Docker Engine فعال | `<...>` | `<PASS/FAIL>` |
| `docker compose version` | Compose v2 | `<...>` | `<PASS/FAIL>` |

## 3. کنترل clone و وابستگی‌ها

| کنترل | نتیجه | شناسه/خلاصه‌ی شاهد |
|---|---|---|
| `git fsck --full` | `<PASS/FAIL>` | `<...>` |
| نصب pnpm با `--frozen-lockfile` | `<PASS/FAIL>` | `<...>` |
| همگام‌سازی uv با `--frozen --group dev` | `<PASS/FAIL>` | `<...>` |
| عدم تغییر lockfile بعد از نصب | `<PASS/FAIL>` | `<git status output>` |
| `pnpm openapi:check` | `<PASS/FAIL>` | `<...>` |

## 4. شواهد Native

| کنترل | نتیجه | شمار/خلاصه |
|---|---|---|
| `python infra/scripts/validate_repository.py` | `<PASS/FAIL>` | `<...>` |
| Frontend static validation | `<PASS/FAIL>` | `<...>` |
| Public environment safety | `<PASS/FAIL>` | `<...>` |
| Frontend lint | `<PASS/FAIL>` | `<...>` |
| Frontend typecheck | `<PASS/FAIL>` | `<...>` |
| Frontend unit tests | `<PASS/FAIL>` | `<TEST_COUNT>` |
| Frontend production builds | `<PASS/FAIL>` | `<...>` |
| Playwright/Axe accessibility | `<PASS/FAIL>` | `<TEST_COUNT>` |
| Backend Ruff | `<PASS/FAIL>` | `<...>` |
| Backend mypy | `<PASS/FAIL>` | `<...>` |
| Backend pytest | `<PASS/FAIL>` | `<TEST_COUNT>` |
| `infra/scripts/verify-native` | `<PASS/FAIL>` | `<LOG_ARTIFACT>` |

## 5. شواهد Docker

| کنترل | نتیجه | شاهد |
|---|---|---|
| placeholder باقی نمانده و credentialهای DSN از charset امن URL استفاده می‌کنند | `<PASS/FAIL>` | فقط نتیجه؛ مقدار ثبت نشود |
| `RELEASE_COMMIT` دقیقاً برابر SHA clone تمیز است | `<PASS/FAIL>` | فقط SHA عمومی |
| `docker compose ... config --quiet` | `<PASS/FAIL>` | `<...>` |
| build همه‌ی imageها | `<PASS/FAIL>` | `<IMAGE_IDS_OR_DIGESTS>` |
| `migrate` با exit code صفر | `<PASS/FAIL>` | `<...>` |
| `storage-init` با exit code صفر | `<PASS/FAIL>` | `<...>` |
| همه‌ی سرویس‌های بلندمدت healthy/running | `<PASS/FAIL>` | `<compose ps>` |
| فقط Nginx روی loopback host port دارد | `<PASS/FAIL>` | `<compose ps>` |
| backend/worker/frontends/Nginx با user غیر-root | `<PASS/FAIL>` | `<inspect summary>` |
| `storage-init` تنها استثنای root، یک‌باره و با capability محدود | `<PASS/FAIL>` | `<inspect summary>` |
| Trader health | `<PASS/FAIL>` | `<HTTP_STATUS>` |
| Admin health | `<PASS/FAIL>` | `<HTTP_STATUS>` |
| API liveness | `<PASS/FAIL>` | `<HTTP_STATUS>` |
| API readiness شامل DB/Redis/storage | `<PASS/FAIL>` | `<HTTP_STATUS>` |
| release metadata با SHA/version مورد انتظار | `<PASS/FAIL>` | `<SAFE_FIELDS_ONLY>` |
| dependency probe احرازشده | `<PASS/FAIL>` | `<SAFE_SUMMARY>` |
| worker probe احرازشده | `<PASS/FAIL>` | `<SAFE_SUMMARY>` |
| بازسازی containerها با `down/up` بدون حذف داده | `<PASS/FAIL>` | `<...>` |
| بقای sentinel مستقل PostgreSQL و storage پس از بازسازی | `<PASS/FAIL>` | `<SAFE_SENTINEL_SUMMARY>` |
| `infra/scripts/verify-docker` | `<PASS/FAIL>` | `<LOG_ARTIFACT>` |

## 6. امنیت و مصنوعات

| کنترل | نتیجه | شاهد |
|---|---|---|
| secret scan مخزن | `<PASS/FAIL>` | `<TOOL/VERSION/REPORT>` |
| scanner داخلی `infra/scripts/scan_secrets.py` | `<PASS/FAIL>` | `<SAFE_SUMMARY>` |
| vulnerability scan وابستگی‌ها | `<PASS/FAIL>` | `<REPORT>` |
| vulnerability scan imageها | `<PASS/FAIL>` | `<REPORT>` |
| SBOM هر image | `<PASS/FAIL>` | `<ARTIFACT_PATH>` |
| ثبت digest imageها و SHA منبع | `<PASS/FAIL>` | `<MANIFEST_PATH>` |
| نبود secret در frontend/`NEXT_PUBLIC_*` | `<PASS/FAIL>` | `<...>` |

یافته‌ی High/Critical نباید بی‌صدا نادیده گرفته شود. برای هر استثنا باید شناسه،
مالک، دلیل، تاریخ سررسید و تأیید امنیت ثبت شود.

## 7. کنترل داده و حذف سیستم قدیمی

- [ ] مشخص شده است که `.local/postgres` و `.local/storage` فقط داده‌ی آزمایشی
  و قابل حذف دارند؛ یا backup رمزگذاری‌شده‌ی لازم مستقل از Git ساخته و restore
  آن آزموده شده است.
- [ ] هیچ `.env`، credential، token، SSH private key یا cache از سیستم قدیمی
  به commit یا archive انتقال وارد نشده است.
- [ ] دسترسی مخزن خصوصی از سیستم مقصد آزموده شده است.
- [ ] SHA remote و clone تمیز یکسان و ثبت شده‌اند.
- [ ] اجرای Native و Docker روی clone تمیز موفق است.
- [ ] مالک پروژه حذف workspace قدیمی را صریحاً تأیید کرده است.
- [ ] پس از حذف، credentialهای مختص سیستم قدیمی revoke/rotate می‌شوند.

## 8. تصمیم نهایی

یکی و فقط یکی را انتخاب کنید:

- [ ] **M1 ACCEPTED** — تمام کنترل‌های اجباری بالا موفق‌اند و شاهد دارند.
- [ ] **M1 NOT ACCEPTED** — موارد باز در جدول زیر باقی مانده‌اند.

| مورد باز | شدت | مالک | موعد | شرط بستن |
|---|---|---|---|---|
| `<...>` | `<...>` | `<...>` | `<...>` | `<...>` |

تصویب‌کننده: `<NAME / ROLE>`
تاریخ: `<YYYY-MM-DD>`
مرجع تصمیم/تیکت: `<REFERENCE>`
