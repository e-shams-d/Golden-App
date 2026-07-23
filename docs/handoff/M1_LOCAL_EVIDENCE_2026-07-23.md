# شواهد محلی M1 در سیستم مبدأ — 2026-07-23

Status: **M1 CANDIDATE / NOT ACCEPTED**

این فایل فقط شواهد قابل اجرا روی سیستم مبدأ را ثبت می‌کند. پذیرش M1 نیازمند
تکرار همین کنترل‌ها از clone تمیز commit انتقال، با نسخه‌های دقیق ابزار و Docker
روی سیستم مقصد است.

## هویت اجرا

- Source commit: همان commit حاوی این سند؛ SHA آن پس از commit در فرم پذیرش مقصد
  ثبت می‌شود
- سیستم‌عامل: Windows
- Node.js: `v24.18.0`
- pnpm: `11.15.1`
- Python محلی: `3.12.10`؛ baseline مقصد `3.12.13` است
- uv: `0.8.22`
- Docker: روی این سیستم در دسترس نیست

## نتایج موفق

| کنترل | نتیجه |
|---|---|
| pnpm lockfile، حالت frozen/offline lock-only | PASS |
| uv lock، حالت check/offline | PASS — 56 package |
| static repository validator | PASS — 196 فایل و 4 Dockerfile |
| high-confidence transfer secret scan | PASS — 238 فایل Git-visible |
| OpenAPI JSON drift check | PASS |
| generated TypeScript OpenAPI drift check | PASS |
| OpenAPI contract tests | PASS — داخل مجموعه backend |
| Ruff | PASS |
| mypy strict | PASS — 31 source file |
| backend pytest | PASS — 44 test |
| Alembic head | PASS — `20260720_0001` |
| lint تمام workspaceهای frontend/package | PASS — 7 workspace |
| TypeScript typecheck | PASS — 2 app و 4 package دارای TypeScript |
| frontend/package unit tests | PASS — 18 test |
| Admin production build | PASS |
| Trader PWA production build | PASS |
| Playwright/Axe smoke قبلی | PASS — 12 test؛ پس از hardening نهایی تکرار نشد |
| PowerShell verification-script parse | PASS |
| POSIX shell verification-script parse | PASS |

آخرین تست accessibility موفق با Chromium cache revision `1208` و override صریح
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` اجرا شده بود. این تست پس از hardening نهایی
به درخواست مالک روی سیستم مبدأ تکرار نشد. اجرای revision قفل‌شده‌ی `1228` از clone
تمیز روی سیستم مقصد اجباری است.

## کنترل‌های اجرا‌نشده یا ناکافی برای پذیرش

- clean clone از commit نهایی و تطبیق SHA با remote خصوصی؛
- Python دقیق `3.12.13` و Chromium دقیق revision `1228`؛
- Compose render/build/up و startup واقعی backend/worker/frontends؛
- migration و `storage-init` داخل Compose؛
- health/readiness و probeهای restricted روی stack واقعی؛
- restart و persistence smoke؛
- بررسی runtime شبکه‌های private، portها و user غیر-root؛
- maintained secret scan، dependency/image vulnerability scan و SBOM؛
- CI adapter واقعی، `CODEOWNERS` و branch protection؛
- ثبت image ID/digest و تکمیل فرم پذیرش.

هیچ `.env`، password، token، rendered Compose یا log دارای داده‌ی محرمانه نباید
به این سند یا بسته‌ی شواهد مقصد اضافه شود.
