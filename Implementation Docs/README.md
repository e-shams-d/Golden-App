# Gold Trade Settlement Platform — Development Documentation

این بسته فقط شامل مستندات موردنیاز تیم توسعه و پیاده‌سازی است. نسخه‌های قدیمی، فایل‌های مقایسه، Diffها، گزارش ویرایش‌های جلسه و آرشیو تاریخی Discovery در این بسته قرار ندارند.

## ترتیب شروع

پیش از کدنویسی، این فایل‌ها را به‌ترتیب بخوانید:

1. `00_Start_Here/16_Implementation_Documentation_Index.md`
2. `00_Start_Here/15_Agent_Implementation_Plan.md`
3. `00_Start_Here/20_Agent_Usage_Instructions.md`
4. `01_Product_and_Domain/00_Master_Implementation_Blueprint.md`
5. `00_Start_Here/Open_ADR_Register.md`
6. `00_Start_Here/Implementation_Kickoff_Checklist.md`
7. سپس اسناد تخصصی مرتبط با Task.

## ساختار پوشه‌ها

- `00_Start_Here` — Index، برنامه پیاده‌سازی، قواعد Agent، ADRها و چک‌لیست شروع.
- `01_Product_and_Domain` — Blueprint، PRD و مدل دامنه.
- `02_Architecture_and_Contracts` — معماری، دیتابیس، API و State Machineها.
- `03_Banking_and_Intelligence` — پردازش فایل‌های بانکی و ماژول AI/OCR آینده.
- `04_Frontend_and_Experience` — Frontend، UI Design System و UX Journeyها.
- `05_Backend_and_Security` — راهنمای Backend و Security/RBAC/Audit.
- `06_DevOps_QA_and_Operations` — Deployment، QA، Runbook تولید و Packaging کلاینت.
- `07_Planning_and_Roadmap` — فازهای آینده و Backlog.

## اصول غیرقابل‌مذاکره

- Phase 1A یک هسته عملیاتی Manual-first و Single-center است.
- Trader PWA و Admin Web دو Application مستقل هستند.
- مبلغ Canonical به‌صورت Integer IRR نگهداری می‌شود و مقدار و واحد ورودی نیز حفظ می‌شوند.
- مدیر نسخه دقیق و تغییرناپذیر `PaymentBatchVersion` و Hash آن را تأیید می‌کند.
- Preview Export، Final Export، Download و Mark-as-sent چهار عملیات جدا هستند.
- Manual Rectangular Crop در Phase 1A الزامی است؛ Auto-segmentation برای فازهای بعد است.
- Matching Candidate، Confirmed Evidence، Payment Result و Publication تصمیم‌های مستقل هستند.
- AI/OCR، Bank API، Native Apps، Chat و Multi-company/SaaS برای Phase 1A الزامی نیستند.
- هر Command مالی حساس باید Idempotency، Concurrency Control، Audit و Transactional Outbox داشته باشد.

## وضعیت تحویل

این بسته **مستندات پیاده‌سازی** است و شامل Source Code، Migrationهای واقعی، OpenAPI تولیدشده، Docker Image یا Secretهای Production نیست. Production readiness فقط پس از اجرای تست‌ها، UAT، Restore Drill، Security Sign-off و تصمیم ADRهای مسدودکننده قابل اعلام است.
