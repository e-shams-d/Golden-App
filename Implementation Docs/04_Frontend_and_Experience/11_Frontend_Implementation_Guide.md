# 11 — Frontend Implementation Guide

## Gold Trade Settlement Platform

**Document ID:** `11_Frontend_Implementation_Guide`  
**Version:** `1.1`  
**Status:** Revised authoritative frontend implementation baseline  
**Language:** English  
**Primary audience:** Frontend engineers, full-stack engineers, UI/UX engineers, QA engineers, security reviewers, technical leads, and coding agents  
**Primary stack:** Next.js App Router, React, TypeScript, Tailwind CSS, TanStack Query, React Hook Form, Zod, TanStack Table, Playwright  
**Applications:** Separate Trader PWA and Admin Web App

### Document control

| Field | Value |
|---|---|
| Product phase | Phase 1A manual operational core, with later-phase extension points |
| Frontend topology | Two separately built and deployed web applications in one monorepo |
| Trader experience | Persian-first, RTL, mobile-first PWA |
| Internal experience | Persian-first, RTL, desktop-first responsive Admin Web App |
| Financial authority | Backend-confirmed, authorized human commands only |
| Manager approval | Exact immutable `PaymentBatchVersion`, not a mutable batch container |
| Manual crop | Required Phase 1A user interface |
| AI/OCR | Optional, feature-flagged, non-authoritative |
| Implementation readiness | Approved as frontend coding baseline; authentication and final brand ADRs remain |

### Change log

| Version | Summary |
|---|---|
| `1.0` | Initial frontend implementation draft. |
| `1.1` | Aligned with documents `00`–`10` v1.1; fixed two-app architecture; added premium gold-trade FinTech direction, explicit IRR/Toman input model, ETag/`If-Match`, mandatory idempotency handling, immutable batch-version approval, exact export handling, Phase 1A manual crop, evidence/publication separation, secure file lifecycle, stale-data UX, production session constraints, accessibility, observability, and stronger automated testing. |

### Related authoritative documents

- `00_Master_Implementation_Blueprint.md`
- `01_Product_Requirements_PRD.md`
- `02_Domain_Model_and_Business_Rules.md`
- `03_System_Architecture.md`
- `04_Database_Schema.md`
- `05_API_Specification.md`
- `06_Workflows_and_State_Machines.md`
- `07_UI_UX_Specification.md`
- `08_Bank_File_and_Result_Processing.md`
- `09_OCR_AI_Module_Specification.md`
- `10_Backend_Implementation_Guide.md`

When examples in this guide conflict with the API, workflow, security, or database specifications, those authoritative contracts take precedence. The conflict must be resolved in documentation before contradictory frontend code is merged.

---

# 1. Purpose

This guide defines how to implement the two frontend applications of the Gold Trade Settlement Platform as safe, modern, high-value financial-operation interfaces.

The frontend must:

1. provide a simple mobile workflow for traders;
2. provide a dense but controlled operational workspace for accountants;
3. provide an exact, trustworthy approval view for managers;
4. support dispatch, read-only, business-admin, and technical-admin roles;
5. display large monetary values without precision loss or unit ambiguity;
6. implement explicit workflow commands rather than generic status editing;
7. preserve revision, version, evidence, correction, and publication history;
8. prevent stale pages and repeated clicks from producing duplicate financial commands;
9. support image/PDF preview and minimal rectangular crop in Phase 1A;
10. remain fully operational with AI, OCR, automatic matching, SMS, and bank APIs disabled;
11. protect mixed bank files and unrelated banking information from trader-facing views;
12. implement a premium, minimal, professional FinTech experience appropriate to the gold trade.

The frontend must preserve valid business outcomes and controls, but it must not reproduce messaging applications, spreadsheets, or paper workflows merely because they are familiar.

---

# 2. Fixed Frontend Decisions

The following are fixed for Phase 1A.

| Topic | Decision |
|---|---|
| Application topology | Two separate applications: `trader-pwa` and `admin-web` |
| Repository | Monorepo with shared packages |
| Framework | Next.js App Router with React and TypeScript |
| Styling | Tailwind CSS plus semantic design tokens and accessible primitives |
| Remote server state | TanStack Query |
| Forms | React Hook Form plus Zod |
| Internal tables | TanStack Table with server-side pagination/filtering/sorting |
| Production language | Persian-first and RTL |
| Trader layout | Mobile-first PWA |
| Internal layout | Desktop-first responsive web app |
| Money transport | Integer values represented as decimal strings in JavaScript-facing DTOs |
| Canonical money unit | IRR |
| Original entry | Value and explicit unit, `IRR` or `TOMAN`, retained |
| Financial mutation UX | Explicit action commands with backend confirmation |
| Idempotency | Mandatory client handling for critical commands |
| Concurrency | ETag/`If-Match` for mutable resources; IDs/hashes for immutable snapshots |
| Manager approval | Exact current `PaymentBatchVersion` and content hash |
| Manual crop | Required Phase 1A workspace |
| Auto-segmentation | Not Phase 1A |
| Publication | Immutable `PaymentResultPublication`, not direct segment exposure |
| Offline financial commands | Forbidden |
| AI authority | Suggestions only |
| Multi-company UI | Phase 4, not Phase 1A |

The exact authentication transport, production font, final logo, final accent colors, and some masking policies remain ADR or brand decisions. The implementation must isolate them behind stable interfaces.

---

# 3. Non-Negotiable Frontend Invariants

## 3.1 The frontend is not the source of financial truth

The frontend may validate, preview, format, warn, and request confirmation. It must not independently calculate or persist final workflow truth.

After a sensitive command:

- wait for the backend response;
- display the server-returned authoritative state;
- refresh affected queries;
- never invent a successful status because a button was clicked;
- never update a financial status optimistically.

## 3.2 Explicit commands, not generic status forms

Forbidden pattern:

```ts
updatePaymentAttempt({ id, status: 'paid' });
```

Required pattern:

```ts
confirmPaymentAttemptPaid({
  attemptId,
  body,
  idempotencyKey,
  ifMatch,
});
```

Financial transitions must map to named API commands such as:

```text
submitPaymentRequest
markRequestEligibleForBatching
finalizeBatchVersion
approveBatchVersion
rejectBatchVersion
generateFinalBankExport
markBankExportSent
confirmPaymentAttemptPaid
confirmPaymentAttemptFailed
replaceEvidenceLink
publishPaymentResult
acknowledgeTraderResult
disputeTraderResult
registerGoldDispatch
```

## 3.3 Current truth versus history

Pages must visually separate:

- current request revision from previous revisions;
- current batch version from superseded versions;
- current approval from historical invalid approvals;
- current evidence link from replaced or revoked links;
- current publication from superseded publications;
- candidates from confirmed evidence;
- technical job success from financial confirmation.

## 3.4 Exact-version manager approval

The manager approves:

```text
Batch ID
Batch Version ID and number
Ordered rows
Row count
Total amount IRR
Bank Profile Version
Bank Mapping Version
Source Bank Account
Content hash
```

A manager page that does not show the exact version and its integrity context is incomplete.

## 3.5 No precision loss

Never use JavaScript floating-point arithmetic for money.

Use:

```ts
type MoneyIntegerString = string;
```

For formatting or exact conversion, use `BigInt` or a validated integer-string utility. Do not pass money through `Number`, scientific notation, or decimal arithmetic.

## 3.6 AI does not collapse review steps

The frontend must keep these actions separate:

```text
View extracted value
Accept/edit extracted value
Choose matching candidate
Create confirmed evidence link
Confirm payment result
Publish result to trader
```

A single “Confirm AI result” action must not perform all of them.

---

# 4. Product Experience and Design Direction

## 4.1 Visual direction

The intended product style is:

```text
Luxury minimalism
+
Professional FinTech
+
High-value gold-trade operations
```

The interface must feel:

- premium;
- restrained;
- precise;
- trustworthy;
- calm under operational pressure;
- connected to the gold trade without becoming decorative.

Avoid:

- black-and-gold casino or cryptocurrency aesthetics;
- jewellery-catalogue styling;
- decorative metallic gradients behind dense data;
- messenger-like conversation layouts for operational records;
- spreadsheet-first screens as the default interaction model;
- excessive glassmorphism, animation, or visual noise.

Gold is a restrained brand accent. Semantic colors remain reserved for success, warning, danger, information, and neutral state.

## 4.2 Density by application

### Trader PWA

- one primary task per screen;
- card-based lists;
- large touch targets;
- simple language;
- low information density;
- minimal tables;
- strong status explanation;
- camera/gallery upload support.

### Admin Web App

- controlled density;
- server-driven tables;
- persistent filters where useful;
- side-by-side document review;
- compact but legible controls;
- keyboard-friendly navigation;
- visible totals and warnings;
- preserved context when moving between queue and detail.

## 4.3 Design tokens

Use semantic tokens rather than hard-coded colors or spacing values.

Required token groups:

```text
surface
text
border
brand-accent
focus
success
warning
danger
info
neutral
status-specific aliases
spacing
radius
elevation
typography
motion
```

The final brand palette may change without requiring business-component rewrites.

---

# 5. Monorepo and Application Architecture

## 5.1 Required repository structure

```text
repo/
  apps/
    trader-pwa/
      app/
      features/
      components/
      public/
      middleware.ts
      next.config.ts
      package.json
    admin-web/
      app/
      features/
      components/
      public/
      middleware.ts
      next.config.ts
      package.json
  packages/
    api-client/
    auth-client/
    domain-contracts/
    design-system/
    financial-ui/
    file-ui/
    localization/
    observability/
    test-support/
    utilities/
    validation/
  tooling/
    eslint-config/
    typescript-config/
    tailwind-config/
  docs/
  package.json
  pnpm-workspace.yaml
  turbo.json
  lockfile
```

Two applications are mandatory because the security surfaces, navigation, bundle composition, cache behavior, and deployment concerns differ materially.

Do not add Admin routes to the Trader PWA and hide them with CSS or client-side permissions.

## 5.2 Shared-package responsibilities

### `api-client`

- OpenAPI-generated or contract-verified DTOs;
- central HTTP transport;
- error normalization;
- ETag extraction;
- `If-Match` handling;
- idempotency headers;
- upload/download helpers;
- request/correlation IDs;
- query-key factories.

### `auth-client`

- authentication-state abstraction;
- session-expiry handling;
- logout and revocation hooks;
- recent-auth workflow;
- CSRF integration when cookie authentication is selected;
- no domain business rules.

### `domain-contracts`

- API DTO types;
- status enums generated or verified against OpenAPI;
- permission constants;
- entity reference types;
- no duplicated server-side transition rules.

### `design-system`

- accessible UI primitives;
- tokenized theme;
- RTL-safe layout primitives;
- dialog, drawer, tooltip, menu, tabs, form controls;
- no product-specific network calls.

### `financial-ui`

- amount display/input;
- IRR/Toman review block;
- IBAN display/input;
- financial confirmation summary;
- status badges;
- batch totals;
- approval fingerprint display;
- conflict and stale-data banners.

### `file-ui`

- upload components;
- image/PDF preview;
- page navigation;
- crop workspace primitives;
- file lifecycle badges;
- secure download controls;
- no direct storage URLs.

### `localization`

- Persian messages;
- status labels;
- Jalali display helpers;
- number-shape policy;
- RTL/LTR utilities;
- translation-key validation.

### `observability`

- frontend error reporting abstraction;
- performance timings;
- privacy-safe analytics events;
- correlation ID propagation.

## 5.3 Dependency direction

Allowed:

```text
apps -> shared packages
feature pages -> feature components -> shared UI
api hooks -> api-client
forms -> validation + domain contracts
```

Forbidden:

- `design-system` importing application features;
- Trader PWA importing Admin components;
- page components calling raw `fetch` directly;
- UI packages importing server secrets;
- feature packages importing another feature's internal files by deep path;
- shared packages storing mutable global financial state.

---

# 6. Next.js Rendering and Routing Strategy

## 6.1 App Router

Use the Next.js App Router for both applications.

Recommended route groups:

```text
app/
  (public)/
  (authenticated)/
  (errors)/
```

The Trader PWA and Admin Web App have separate root layouts, manifests, middleware, metadata, and deployment artifacts.

## 6.2 Server and client components

Use Server Components for:

- static shells;
- initial authenticated layout when compatible with the auth ADR;
- read-only page framing;
- metadata;
- safe initial data hydration where it improves performance.

Use Client Components for:

- forms;
- data tables;
- dialogs;
- TanStack Query hooks;
- file upload;
- crop interactions;
- dynamic filters;
- status-command actions;
- PWA-only browser APIs.

Do not make the entire application a Client Component merely for convenience.

## 6.3 Route protection

Protection must occur before sensitive content is rendered.

Required behavior:

- unauthenticated users are redirected to login;
- forbidden users receive a dedicated permission state;
- sensitive Admin content must not flash before permission evaluation;
- route metadata can declare required permissions;
- backend authorization remains mandatory for every API call.

## 6.4 Route maps

### Trader PWA

```text
/login
/recover-account
/pending-approval
/home
/requests
/requests/outgoing
/requests/outgoing/new
/requests/outgoing/[requestId]
/requests/gold
/requests/gold/new
/requests/gold/[orderId]
/results
/results/[publicationId]
/notifications
/profile
```

### Admin Web App

```text
/login
/dashboard
/work-queues
/traders
/traders/[traderId]
/beneficiaries
/beneficiaries/[beneficiaryId]
/payment-requests
/payment-requests/[requestId]
/payment-batches
/payment-batches/[batchId]
/payment-batches/[batchId]/versions/[versionId]
/bank-exports/[exportId]
/payment-attempts
/payment-attempts/[attemptId]
/bank-result-bundles
/bank-result-bundles/upload
/bank-result-bundles/[bundleId]
/receipt-segments/[segmentId]
/manual-reviews
/manual-reviews/[taskId]
/gold-sale-orders
/gold-sale-orders/[orderId]
/bank-statements
/bank-statements/[statementId]
/dispatch
/reports
/audit
/settings/users
/settings/roles
/settings/banks
/settings/source-accounts
/settings/features
/settings/retention
/system/jobs
```

Role and permission filtering controls visibility, but routes still return a secure forbidden state when accessed directly.

---

# 7. API Contract and Client Implementation

## 7.1 OpenAPI-derived types

Prefer generating request and response types from the checked-in OpenAPI contract.

Rules:

- generated files are not manually edited;
- breaking API changes fail CI;
- frontend-specific view models wrap DTOs rather than replacing contracts;
- status enums are not recreated as arbitrary strings;
- money values remain integer strings when returned by the API contract;
- timestamps remain ISO strings until formatted for display.

## 7.2 Central transport

All HTTP calls pass through one transport layer.

```ts
export type ApiRequestOptions<TBody> = {
  method: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  path: string;
  body?: TBody;
  idempotencyKey?: string;
  ifMatch?: string;
  recentAuthToken?: string;
  signal?: AbortSignal;
};
```

The transport handles:

- base URL;
- credentials mode according to authentication ADR;
- CSRF header when required;
- JSON and multipart serialization;
- response parsing;
- ETag extraction;
- correlation IDs;
- normalized errors;
- safe unauthorized handling;
- no automatic replay of sensitive commands.

## 7.3 Standard error type

```ts
export type ApiError = {
  status: number;
  code: string;
  message: string;
  details?: Record<string, unknown>;
  fieldErrors?: Record<string, string[]>;
  requestId?: string;
};
```

Required mappings:

| HTTP | Frontend behavior |
|---:|---|
| `400` | Business or input error; show actionable message |
| `401` | End protected session and route to login or reauthentication |
| `403` | Permission state; do not silently hide server denial |
| `404` | Not-found or ownership-safe not-found state |
| `409` | Domain conflict or idempotency-key reuse |
| `412` | Version conflict; show stale-data recovery |
| `413` | File-size error |
| `422` | Map field validation errors |
| `428` | Required `If-Match` or idempotency key missing; treat as client bug plus user-safe message |
| `500+` | Generic safe message with request ID |

## 7.4 ETag handling

For mutable resources, detail responses must retain the ETag returned by the server.

```ts
export type VersionedResource<T> = {
  data: T;
  etag: string;
};
```

A mutation that changes the resource sends:

```http
If-Match: "rv-7"
```

Do not derive `If-Match` from a displayed status or local timestamp.

When a mutation returns a new ETag, replace the cached version atomically.

## 7.5 Immutable snapshots

Immutable resources such as `PaymentBatchVersion` are controlled by:

- version ID;
- batch current-version relationship;
- content hash;
- approval ID;
- export ID.

Do not send `If-Match` for an immutable version unless the API explicitly requires it. Send the expected content hash where specified.

## 7.6 Idempotency manager

Critical commands use a stable idempotency key for one logical user action.

```ts
export type CommandSubmission = {
  key: string;
  state: 'idle' | 'submitting' | 'checking' | 'completed' | 'failed';
};
```

Rules:

1. Generate the key before the first network attempt.
2. Reuse the same key after a network timeout when checking/retrying the same logical command.
3. Generate a new key only when the user intentionally changes the command payload or starts a new action.
4. Never generate a new key automatically after an unknown outcome.
5. Disable repeated clicks while the command is in flight.
6. Do not persist sensitive command payloads in local storage.
7. A page reload may query the server for current state instead of blindly resubmitting.

Required UX during uncertain outcome:

```text
Checking whether the action was completed…
```

## 7.7 Query-key factories

Use typed factories.

```ts
paymentRequestKeys.detail(requestId)
paymentRequestKeys.revisions(requestId)
paymentBatchKeys.detail(batchId)
paymentBatchKeys.version(batchId, versionId)
paymentBatchKeys.approvalView(batchId, versionId)
bankExportKeys.detail(exportId)
bankResultBundleKeys.detail(bundleId)
publicationKeys.current(requestId)
manualReviewKeys.list(filters)
```

Avoid free-form query-key arrays scattered throughout pages.

## 7.8 Cache and invalidation rules

After commands, invalidate or update only authoritative affected data.

Examples:

- Submit request: request detail, request list, trader dashboard, accountant queue, notifications.
- Finalize batch version: batch detail, version detail, approval queue.
- Approve version: version, approval view, batch, manager queue, export eligibility.
- Mark export sent: export, batch, attempts, related requests, work queues.
- Confirm attempt result: attempt, request aggregate, batch aggregate, review tasks.
- Replace evidence: segment, evidence links, attempt, current publication, correction queue.
- Publish result: request, publication list/current, trader result list, notifications.

Never show a financial result using only an optimistic cache patch.

---

# 8. Authentication, Session, and Recent Authentication

## 8.1 ADR-neutral auth client

The frontend must support the selected secure transport without embedding authentication logic into domain features.

Acceptable implementation characteristics:

- secure HTTP-only cookie session, or another approved transport;
- explicit session expiry;
- revocation support;
- logout;
- account recovery;
- CSRF protection when applicable;
- no long-lived token in `localStorage`;
- no tokens in URLs;
- no secrets in frontend environment variables.

## 8.2 Session lifecycle

The application must distinguish:

```text
unknown
unauthenticated
authenticated
expired
revoked
reauthentication_required
```

When a session expires:

- block access to protected data;
- clear in-memory sensitive caches;
- preserve unsent non-sensitive form input only when safe;
- do not replay a financial command automatically after login;
- return the user to a safe page with a message.

## 8.3 Recent authentication

Manager approval and other configured high-risk actions call the reauthentication endpoint.

Flow:

```text
User initiates sensitive action
→ API indicates recent authentication required or UI pre-check detects it
→ reauthentication dialog
→ backend returns short-lived recent-auth context
→ exact command is submitted with original idempotency key
```

The UI must not treat opening the dialog as approval.

## 8.4 Permission model

Use permission constants returned by the backend.

```tsx
<PermissionGate permission="payment_batch.approve">
  <ApproveBatchVersionButton />
</PermissionGate>
```

`PermissionGate` improves UX but does not authorize API requests.

A technical administrator must not automatically receive financial permissions.

---

# 9. Localization, RTL, Dates, and Numeric Safety

## 9.1 Persian-first implementation

All production copy must come from translation resources.

Forbidden:

```tsx
<button>Approve batch</button>
```

Required:

```tsx
<button>{t('batch.actions.approveVersion')}</button>
```

Translation keys must cover:

- statuses;
- actions;
- error codes;
- validation messages;
- warnings;
- empty states;
- accessibility labels;
- file lifecycle;
- publication history;
- AI suggestion labels.

## 9.2 RTL and bidirectional text

Set `dir="rtl"` at application level for Persian.

Use explicit LTR wrappers for:

- IBAN;
- tracking numbers;
- hashes;
- UUID-like references;
- file checksums;
- technical error references;
- Latin filenames when needed.

Test mixed Persian and Latin strings for visual reordering errors.

## 9.3 Dates

- Display business dates in Jalali format.
- Display exact time on approval, audit, export, payment-result, dispatch, and correction screens.
- Keep ISO/UTC timestamps in DTOs.
- Use relative time only as secondary text.
- Store filters in stable URL values, not localized display strings.

## 9.4 Digit policy

The UI may display Persian digits according to the approved design, but:

- copied IBANs and tracking numbers must retain correct Latin characters;
- form parsers must accept Persian, Arabic, and Latin digits;
- API payloads use canonical Latin-digit integer strings;
- identifiers must never be transformed in a way that changes meaning.

---

# 10. Money Components and Rules

## 10.1 Money type

```ts
export type MoneyUnit = 'IRR' | 'TOMAN';

export type EnteredMoney = {
  value: string;
  unit: MoneyUnit;
  amountIrr: string;
};
```

## 10.2 `AmountDisplay`

Required behavior:

- accept integer-string IRR;
- format with grouping separators;
- show explicit unit;
- optionally show Toman equivalent;
- optionally show amount in words on sensitive screens;
- never abbreviate critical totals to `34.4B` as the only display;
- support copy without hidden characters;
- remain readable in RTL.

## 10.3 `AmountInput`

Required fields:

```text
Amount value
Explicit unit selector: Toman | Rial
Canonical IRR preview
Toman equivalent
Validation/warning area
```

Rules:

- no silent unit inference;
- no decimal values;
- no negative values unless a dedicated adjustment workflow permits them;
- preserve the user's entered value and selected unit;
- use integer-string parsing;
- reject scientific notation;
- normalize Persian/Arabic digits;
- show unusually large/small warnings without changing the value;
- backend remains final validator.

## 10.4 Financial review block

Before high-risk submission, show:

```text
Entered: 3,440,000,000 Toman
Canonical: 34,400,000,000 IRR
Equivalent: 3,440,000,000 Toman
Beneficiary: …
IBAN: …
```

For manager approval and final export, show exact IRR total and Toman equivalent prominently.

---

# 11. Shared Domain Components

## 11.1 `StatusBadge`

The component receives an entity type and a backend enum.

It must:

- use centralized Persian labels;
- include text, not color alone;
- expose an accessible description;
- distinguish current, superseded, replaced, rejected, failed, and warning states;
- not invent aggregate statuses locally.

## 11.2 `EntityReference`

Displays public references rather than raw UUIDs, with optional copy action and LTR isolation.

## 11.3 `IbanDisplay` and `IbanInput`

- grouped visual display;
- canonical unspaced copy;
- LTR direction;
- optional policy-driven masking;
- no claim of account-owner verification in Phase 1A;
- duplicate warning is separate from structural validation.

## 11.4 `FinancialConfirmDialog`

Required content:

- exact action;
- entity reference;
- current status;
- target status or effect;
- trader;
- beneficiary;
- amount in IRR and Toman;
- IBAN where relevant;
- warnings;
- reason field when required;
- recent-auth step where required;
- clear cancel and confirm labels.

The confirm button remains disabled until required data and acknowledgements are complete.

## 11.5 `VersionConflictPanel`

When `412 VERSION_CONFLICT` occurs:

- preserve the user's non-sensitive form values;
- explain that another user changed the record;
- show latest server version;
- offer reload/compare;
- do not auto-merge sensitive fields;
- do not automatically replay the command with the new ETag.

## 11.6 `ImmutableVersionBanner`

Used for finalized batch versions, request revisions, exports, and publications.

It states that the version is read-only and links to the replacement/current version where applicable.

## 11.7 `AuditTimeline`

- current truth remains visually primary;
- audit entries are collapsible;
- old and new values are safely formatted;
- sensitive metadata is permission-protected;
- no raw stack traces or secret values;
- timestamps are exact.

## 11.8 `StructuredReasonForm`

Use for:

- request correction;
- rejection;
- cancellation;
- failed payment reason;
- evidence replacement;
- result dispute;
- sensitive override;
- dispatch issue.

This replaces internal chat for Phase 1A.

---

# 12. File Upload, Lifecycle, Preview, and Download

## 12.1 File lifecycle UI

Display server lifecycle states:

```text
selected
uploading
uploaded_validating
quarantined
available
processing_preview
preview_ready
processing_failed
archived
retention_pending
deleted_by_policy
```

A successful network upload does not mean the file is available for use.

## 12.2 Upload rules

The shared uploader must:

- show accepted MIME types and size limits from server configuration;
- perform convenience checks without replacing server validation;
- show progress;
- support cancellation before finalization where safe;
- use idempotent upload finalization where specified;
- show checksum/duplicate warnings returned by the backend;
- never expose a raw storage key;
- avoid persistent browser storage of file contents.

## 12.3 Secure downloads

All downloads use authorized API endpoints or short-lived signed URLs issued after authorization.

The client must:

- avoid embedding permanent file URLs;
- handle expired signed URLs by requesting a new authorized URL;
- display the server-provided safe filename;
- log privacy-safe download events when required;
- never allow a Trader page to construct an Admin file URL.

## 12.4 Preview

### Images

- lazy-load;
- zoom and pan;
- rotation display;
- secure open/download;
- show original versus derived status.

### PDF

- page navigation;
- lazy page rendering;
- zoom and rotate;
- download fallback;
- no full-document exposure to traders unless explicitly published.

### Excel

- use backend-provided metadata or parsed preview;
- do not parse full sensitive workbooks in the browser by default;
- distinguish Preview Export from Final Export.

## 12.5 File type labels

Clearly identify:

```text
Original upload
Normalized page
Manual crop
External evidence
Preview export
Final bank export
Trader share card
Superseded publication file
```

---

# 13. Trader PWA Implementation

## 13.1 PWA shell

Required:

- responsive mobile-first layout;
- installable manifest when supported;
- safe update prompt;
- bottom navigation;
- offline shell for non-sensitive static pages only;
- no offline financial command queue;
- no sensitive API response caching in service worker storage;
- camera/gallery upload support;
- accessible touch targets.

Recommended bottom navigation:

```text
Home
Requests
Results
Notifications
Account
```

## 13.2 Authentication and pending approval

A pending trader may:

- view pending status;
- view submitted profile summary;
- view center contact details;
- log out.

A pending or suspended trader may not create new financial requests.

## 13.3 Trader dashboard

Display:

- items needing trader action;
- outgoing requests in progress;
- results ready;
- disputed results;
- gold-sale orders in progress;
- recent activity.

Do not expose internal queue terminology, approval hashes, or bank mapping details.

## 13.4 Beneficiary selection and management

Beneficiary is reusable and does not contain a payment amount.

Trader workflow:

```text
Choose existing beneficiary
or
Create beneficiary
→ Review name and IBAN
→ Enter request-specific amount
```

Show duplicate warnings, but do not automatically merge beneficiaries.

## 13.5 Outgoing payment request draft

Required fields:

- beneficiary;
- amount value;
- explicit unit;
- description/reason where applicable;
- optional attachment;
- optional business metadata allowed by the API.

Actions:

- save draft;
- submit to center;
- save and create another.

The review step shows the current immutable revision that will be submitted.

## 13.6 Request revisions

The detail page must show:

- current revision number;
- current amount, unit, beneficiary, and IBAN snapshot;
- status;
- correction request from the center;
- revision history;
- whether a historical revision was used by an attempt.

When correcting a request, the form creates a new revision rather than editing historical data.

## 13.7 Request status display

Use trader-friendly labels mapped from canonical states, including:

```text
draft
submitted_to_center
under_accountant_review
needs_trader_correction
eligible_for_batching
batched
sent_to_bank
partially_paid
paid
failed
retry_required
result_ready_for_trader
result_published
trader_acknowledged
trader_disputed
cancelled
closed
```

Some internal distinctions may be grouped in the trader label, but the frontend must not create incompatible states.

## 13.8 Result publication view

Trader sees a `PaymentResultPublication`, not a raw Receipt Segment.

Required display:

- publication version;
- current or superseded label;
- beneficiary snapshot;
- exact amount;
- masked/full IBAN according to policy;
- bank and tracking data;
- attempt summary;
- safe evidence;
- publication time;
- download/share action;
- acknowledge action;
- dispute action.

A superseded publication remains visible in history with a clear warning that it is no longer current.

## 13.9 Share behavior

Prefer backend-generated share files.

The frontend may invoke the Web Share API, but must not generate a share card from stale client-only data.

The share output must not include:

- unrelated people;
- mixed bank bundle content;
- internal notes;
- full audit history;
- AI confidence;
- technical identifiers not intended for the trader.

## 13.10 Dispute

Use structured issue types and a required explanation where appropriate.

Submitting a dispute creates an internal review task; it does not reverse the payment automatically.

---

# 14. Admin Web App Shell and Work Queues

## 14.1 Shell

Required:

- right-side RTL navigation or approved RTL layout;
- top bar with current role, notifications, session controls;
- global search where authorized;
- breadcrumb and entity reference;
- responsive behavior for manager tablets;
- no Trader-only navigation.

## 14.2 Work queues

The default internal experience is queue-driven.

Queue groups include:

```text
Trader approvals
Outgoing request review
Eligible for batching
Batch version corrections
Manager approvals
Final exports ready
Bank results pending
Unmatched evidence
Payment confirmations
Failed/retry attempts
Trader disputes
Incoming payment verification
Gold dispatch
Sensitive corrections
Processing failures
```

Each queue item includes:

- reference;
- trader;
- amount;
- reason for entry;
- status;
- waiting time;
- warnings;
- assignee;
- priority;
- next allowed action.

## 14.3 Queue safety

- server-side pagination/filtering;
- no bulk paid confirmation;
- no bulk manager approval;
- assignment uses `If-Match`;
- stale rows are visibly invalidated;
- opening a row preserves queue filters and scroll position;
- sensitive actions occur on detail/review screens with sufficient context.

---

# 15. Payment Request Review Workspace

## 15.1 Layout

Recommended desktop layout:

```text
Header: reference, status, trader, amount, age, warnings
Left: request/revision details and attachments
Right: beneficiary, validation, duplicate context, actions
Bottom/Drawer: attempts, timeline, audit, revision history
```

## 15.2 Accountant actions

- start review;
- request trader correction;
- mark current revision eligible for batching;
- cancel where policy permits;
- add structured internal note.

Use `Mark eligible for batching`, not `Manager approve request`.

## 15.3 Sensitive field corrections

An internal user must not silently overwrite submitted amount, beneficiary, or IBAN.

Material corrections create a new request revision with:

- before/after comparison;
- reason;
- actor;
- timestamp;
- updated ETag.

## 15.4 Duplicate warnings

Warnings may include:

- same trader, IBAN, and amount recently submitted;
- same beneficiary and amount;
- same attachment checksum;
- beneficiary blocked/inactive;
- request already allocated.

Warnings do not silently reject the request unless the backend returns a blocking error.

---

# 16. Batch Builder and Versioning

## 16.1 Batch preview

Flow:

```text
Filter eligible requests
→ select requests
→ call batch preview endpoint
→ review generated attempts and splitting
→ create batch container and draft version
```

The frontend must not reproduce splitting rules locally as authoritative logic. It may show the server preview.

## 16.2 Batch builder columns

Required:

- selection;
- request reference;
- request revision;
- attempt sequence;
- trader;
- beneficiary;
- IBAN;
- amount IRR;
- Toman equivalent;
- source bank account;
- bank-profile/mapping context;
- validation warnings;
- conflict/allocation state.

## 16.3 Draft versions

A draft version is editable through replacement/version APIs only.

Display:

- version number;
- draft/current/superseded state;
- exact total;
- row count;
- generated-at time;
- creator;
- bank profile version;
- mapping version;
- source account;
- validation summary.

## 16.4 Finalization

Before finalization, show a full review summary.

Finalization:

- uses idempotency;
- uses current batch ETag where required;
- produces an immutable version and content hash;
- removes normal edit controls;
- creates or updates the manager approval queue.

After finalization, the only correction action is `Create replacement version`.

## 16.5 Replacement version

Show differences from the previous version:

- added/removed attempts;
- changed request revisions;
- amount changes;
- beneficiary/IBAN changes;
- bank/mapping/source-account changes;
- total and row-count changes.

A historical approval does not carry forward.

---

# 17. Manager Batch Approval

## 17.1 Approval view

The manager view must be purpose-built and read-only.

Show:

```text
Batch reference
Current version number
Version ID/reference
Exact total IRR
Toman equivalent
Amount in words where available
Row count
Request count
Trader count
Beneficiary count
Bank
Bank Profile Version
Mapping Version
Source Bank Account
Creator/finalizer
Finalized time
Content-hash fingerprint
Validation warnings
Full ordered item list
Preview export marked non-sendable
```

## 17.2 Stale approval protection

When the page is no longer current:

- show a blocking stale-version banner;
- disable approval/rejection submission;
- link to the current version;
- retain the old view only for history/comparison;
- never silently update the manager to a new version while preserving an old confirmation dialog.

## 17.3 Approval command

Flow:

```text
Open exact approval view
→ inspect warnings and rows
→ recent authentication if required
→ open financial confirmation dialog
→ submit expected content hash + note + idempotency key
→ display backend-confirmed approval
```

Rejection requires a reason.

## 17.4 Separation of duty

When configured, the UI must explain why the creator/finalizer cannot approve their own version. Do not simply hide the button without context.

---

# 18. Bank Export UI

## 18.1 Preview export

Preview export must display a persistent banner:

```text
PREVIEW — NOT APPROVED FOR BANK SUBMISSION
```

Preview cannot be marked sent and must not appear in a normal final-export download action.

## 18.2 Final export

Final export detail includes:

- export reference;
- exact batch/version;
- approval reference;
- bank/mapping version;
- source account;
- filename;
- row count;
- total;
- content hash;
- file checksum;
- integrity state;
- generation time;
- download history where authorized;
- sent marker.

## 18.3 Integrity failure

When an export is quarantined:

- block download for bank submission;
- show a danger banner;
- show safe reason and request ID;
- link to the high-priority review task;
- do not offer “download anyway”.

## 18.4 Mark as sent

The command applies to an exact export.

Confirmation shows:

```text
Export reference
Batch/version
Filename
Total
Row count
Checksum/integrity status
Sent time
Submission channel
Note
```

Display the explicit statement:

```text
Downloading the file does not mean it was sent to the bank.
```

---

# 19. Bank Result Bundle Review Workspace

## 19.1 Desktop workspace

Required layout:

```text
Top bar:
  bundle context, bank, received date, progress, unresolved navigation

Left pane:
  image/PDF/Excel preview, pages, zoom, pan, rotation, crop controls

Right pane:
  selected segment/result form, attempt search, structured values, actions

Bottom drawer:
  candidates, confirmed evidence, files, history, tasks, AI output if enabled
```

A tab fallback may be used on smaller screens, but desktop accountant workflow should support side-by-side review.

## 19.2 Mixed bundles

The UI must allow:

- no batch selected at upload;
- links to multiple batches;
- evidence from multiple traders;
- unresolved items;
- overlapping source files;
- closure with unresolved reasons when policy allows.

Never assume one bundle equals one batch.

## 19.3 Attempt search

Search by:

- attempt reference;
- request reference;
- trader;
- beneficiary;
- IBAN;
- exact amount;
- batch;
- export;
- tracking number;
- sent date.

Repeated equal amounts must show sufficient context to prevent selecting the wrong attempt.

---

# 20. Phase 1A Manual Crop Workspace

## 20.1 Required capabilities

- image and PDF-page display;
- page selection;
- zoom;
- pan;
- 90-degree rotation controls;
- rectangular selection;
- normalized coordinate calculation;
- crop preview;
- create Receipt Segment;
- render-status display;
- retry failed render;
- external-evidence fallback;
- preserve original source.

## 20.2 Coordinate model

Send normalized decimal-string coordinates:

```ts
export type NormalizedRect = {
  x: string;
  y: string;
  width: string;
  height: string;
};
```

Values must be between zero and one. The UI must not send only display-pixel coordinates.

## 20.3 Crop command flow

```text
Select authorized source file/page
→ choose rotation/view
→ select rectangle
→ preview crop
→ submit source dimensions + normalized rectangle + idempotency key
→ show pending segment
→ poll render status
→ show available crop or retry/manual fallback
```

## 20.4 Accessibility

Provide alternatives to drag-only interaction:

- keyboard-adjustable crop handles where practical;
- numeric/step controls for boundaries;
- explicit zoom and rotate buttons;
- visible focus;
- clear instructions;
- reset action.

## 20.5 Privacy review

Before evidence publication, require a human privacy check:

- no unrelated names;
- no unrelated IBANs;
- no other transactions;
- correct attempt selected;
- crop is legible and sufficient.

Crop creation alone does not publish evidence or confirm payment.

---

# 21. Matching Candidates and Confirmed Evidence

## 21.1 Candidate display

Candidate cards show:

- extracted values;
- candidate attempt;
- deterministic reasons;
- mismatches;
- score labeled as candidate score, not payment certainty;
- warnings;
- source/provenance;
- accept-for-confirmation and reject actions.

## 21.2 Candidate acceptance

`Accept for confirmation` does not create a Paid result.

The next step creates a `ConfirmedEvidenceLink` through an explicit confirmation form.

## 21.3 Evidence-link form

Show:

- attempt snapshot;
- segment/evidence preview;
- link type: primary or supplementary;
- existing active primary evidence;
- duplicate/conflict warnings;
- reason/note where required.

## 21.4 Replace evidence

Use `Replace evidence`, not delete.

Display:

- existing link;
- replacement evidence;
- before/after preview;
- replacement reason;
- current publication impact;
- trader-notification impact;
- required sensitive review.

The old link remains historical.

---

# 22. Payment Attempt Result Confirmation

## 22.1 Attempt detail

Show:

- parent request and exact request revision;
- batch/version/export context;
- trader;
- beneficiary/IBAN snapshot;
- attempt amount;
- status;
- sent time;
- result details;
- evidence links;
- publication relationship;
- retry/correction history.

## 22.2 Confirm paid

Before submission show:

```text
Attempt amount
Entered paid amount
Request total
Authoritative paid total before command
Expected paid total after command
Expected remaining amount
Expected request status
Beneficiary
IBAN
Evidence preview
Exception policy if evidence absent
```

The UI must block client-side obvious overpayment, but the backend remains authoritative.

## 22.3 Overpayment

When the backend returns reconciliation-required:

- do not offer “confirm anyway”;
- show excess amount;
- create/link to review workflow;
- refresh attempt and request state;
- preserve entered note for review where safe.

## 22.4 Confirm failed

Require a structured reason and show retry implications.

## 22.5 Retry

Retry form shows:

- failed attempt;
- failure reason;
- remaining amount;
- current request revision;
- differences from the failed attempt snapshot;
- new attempt amount;
- requirement for a later batch version and manager approval.

Beneficiary or IBAN cannot be edited directly inside the retry dialog. A new request revision is required first.

## 22.6 Text-only confirmation

When allowed by production policy:

- permission-gated;
- strong warning;
- detailed reason required;
- clearly labeled in audit/reports;
- not visually equivalent to evidence-backed confirmation.

---

# 23. Result Publication and Correction

## 23.1 Publication preview

Before publication, show the exact trader-visible snapshot:

- beneficiary;
- amount;
- IBAN masking;
- status;
- bank/tracking data;
- selected evidence;
- share file preview;
- privacy checklist;
- publication version.

## 23.2 Publication command

Publication uses:

- explicit endpoint;
- idempotency key;
- current request ETag where required;
- backend-generated immutable snapshot;
- no optimistic visibility update.

## 23.3 Correction of published result

Flow:

```text
Inspect current publication
→ create sensitive review/correction reason
→ replace result/evidence through authorized workflow
→ manager or dual-control decision if configured
→ preview publication N+1
→ publish N+1
→ previous publication becomes superseded
→ trader notification
```

Do not edit the active publication in place.

## 23.4 Trader notification

A material correction must generate a visible notification and current/superseded labels. The frontend must not conceal the existence of a previous version.

---

# 24. Incoming Payment and Gold-Sale Frontend

## 24.1 Gold-sale order

Display:

- gold type;
- weight and unit;
- purity/carat;
- pricing version;
- expected amount;
- incoming payment total;
- outstanding/overpaid amount;
- verification state;
- dispatch/settlement state;
- cancellation/closure history.

## 24.2 Pricing versions

Center pricing is immutable/versioned. Show current pricing prominently and history separately.

## 24.3 Incoming receipt

Trader submission does not mean payment is confirmed.

Accountant review compares receipt information with immutable bank-statement import rows.

## 24.4 Statement import run

Frontend displays:

- original statement file;
- import-run version;
- bank mapping version;
- row counts;
- parse errors;
- duplicate warnings;
- raw and normalized values where authorized;
- confirmed/rejected matching history.

Reparse creates a new import run; it does not overwrite old rows.

## 24.5 Dispatch guard

The dispatch action is disabled with an explanation until backend-provided payment/override guards are satisfied.

Do not implement the guard only in the frontend.

---

# 25. Tables, Filters, Search, and Saved Context

## 25.1 Server-side behavior

All large internal lists use:

- server-side pagination;
- server-side sorting;
- server-side filtering;
- stable row IDs;
- bounded page sizes;
- loading, empty, and error states.

Never load thousands of financial rows into browser memory.

## 25.2 URL state

Represent shareable operational filters in the URL:

- status;
- trader;
- bank;
- date range;
- amount range;
- action required;
- warning type;
- assignee;
- publication state.

Do not place sensitive free-text notes in URLs.

## 25.3 Selection safety

- clear selection when filters materially change unless the user confirms retaining it;
- show selected totals;
- prevent hidden selected rows from being unknowingly submitted;
- revalidate batch preview on server;
- use stable IDs, never visible row index.

## 25.4 Saved views

Saved views are optional in Phase 1A. When implemented, they store filter definitions, not private response data.

---

# 26. Forms and Mutation UX

## 26.1 Form standards

Use React Hook Form and Zod.

Forms must:

- validate for usability;
- map backend field errors;
- preserve safe input after recoverable errors;
- warn about unsaved changes;
- block double submission;
- expose the exact command effect;
- use server truth after submit;
- retain ETag associated with the edited resource.

## 26.2 Draft autosave

Do not autosave sensitive financial fields unless explicitly designed.

A draft autosave must:

- be visible;
- use ETag and conflict handling;
- not submit a request;
- not create hidden revisions on every keystroke;
- avoid storing values in browser persistent storage.

## 26.3 Confirmation dialogs

A generic “Are you sure?” is insufficient for high-value actions.

Show the key facts and consequences.

## 26.4 Unsaved-change behavior

Do not clear a form after an unknown network result. First determine whether the command completed using the same idempotency context or by refreshing current server state.

---

# 27. Notifications and Background Jobs

## 27.1 In-app notifications

Phase 1A uses in-app notifications and work queues.

Do not require SMS or external messengers.

## 27.2 Delivery behavior

Notifications are eventually delivered through the backend outbox.

The UI must tolerate:

- state change visible before notification appears;
- duplicate delivery attempts;
- delayed notification;
- already-resolved target.

The target resource remains source of truth.

## 27.3 Background job status

For preview, crop, export, import, report, and optional AI jobs, show:

```text
queued
running
succeeded
partially_succeeded
retry_scheduled
failed
cancelled
manual_fallback_required
```

Do not interpret technical `succeeded` as financial success.

## 27.4 Polling

Use bounded polling with backoff for active jobs. Stop polling on terminal state, route exit, or visibility timeout. Avoid permanent high-frequency polling.

---

# 28. Offline and PWA Safety

## 28.1 Allowed offline behavior

- static shell;
- app icon and manifest;
- safe help content;
- previously loaded non-sensitive layout assets;
- offline status message.

## 28.2 Forbidden offline behavior

Do not queue offline:

- request submission;
- manager approval;
- payment confirmation;
- evidence replacement;
- publication;
- mark export sent;
- dispatch confirmation;
- retention commands.

Do not cache sensitive API JSON, bank files, receipts, or publications in a service worker cache for offline use.

## 28.3 PWA update

Do not silently replace the application during a sensitive form or approval review. Show an update prompt and apply after the user reaches a safe point.

---

# 29. Security and Privacy

## 29.1 Browser storage

Forbidden in persistent browser storage:

- auth secrets;
- long-lived tokens;
- file blobs;
- full bank responses;
- IBAN/beneficiary caches;
- financial command payloads;
- raw audit data.

Use memory and server refetching where possible.

## 29.2 Logs and error reporting

Never send to console or third-party telemetry:

- IBAN;
- national ID;
- beneficiary names tied to transaction details;
- receipt images;
- full amounts with entity identifiers;
- notes;
- tokens;
- signed URLs.

## 29.3 Analytics

Product analytics must be privacy-safe.

Allowed examples:

- page type viewed;
- command success/failure category;
- duration bucket;
- feature flag enabled;
- generic validation-error code.

Disallowed payloads include financial record content or identities.

## 29.4 XSS and content rendering

Render names, descriptions, notes, filenames, and bank text as plain text. Sanitize any future rich text. Never use unsanitized `dangerouslySetInnerHTML`.

## 29.5 Tabnabbing and downloads

Secure external/open-new-tab links with appropriate browser protections. Do not expose bearer credentials in URLs.

## 29.6 Clipboard

Copy actions for IBAN, tracking number, and references must copy exact canonical values and show a confirmation. Avoid copying unrelated surrounding text.

---

# 30. Accessibility

Minimum acceptance baseline:

- keyboard navigation;
- visible focus;
- semantic headings;
- form labels and descriptions;
- field-error association;
- accessible dialogs with focus trap and return focus;
- status not conveyed by color alone;
- semantic tables;
- screen-reader labels for icon actions;
- RTL-correct tab order;
- touch targets suitable for mobile;
- reduced-motion support;
- non-drag crop controls;
- sufficient contrast;
- zoom without content loss.

Financial actions must be usable without a mouse in the Admin Web App where practical.

---

# 31. Performance and Reliability

## 31.1 Bundle boundaries

Trader PWA must not include Admin table, crop, audit, or settings bundles.

Admin crop/PDF components must be lazy-loaded.

## 31.2 Data fetching

- use server pagination;
- cancel obsolete requests;
- avoid request waterfalls;
- prefetch next queue item where safe;
- do not aggressively cache mutable financial details;
- show last-refreshed time on long-lived approval/review screens.

## 31.3 File preview

- thumbnails first;
- lazy pages;
- virtualize long page lists if necessary;
- release object URLs;
- do not decode huge images repeatedly;
- show fallback download when renderer fails.

## 31.4 Resilience

- preserve safe user input after transient failures;
- display request ID;
- distinguish offline from server error;
- use error boundaries around heavy preview components;
- a preview failure must not lose the underlying uploaded file.

---

# 32. Frontend Observability

Track privacy-safe metrics:

- page load and interaction performance;
- API error code counts;
- version-conflict frequency;
- idempotent replay/unknown-outcome frequency;
- upload failures by category;
- crop render failures;
- export integrity blocks;
- work-queue age display failures;
- unhandled exceptions;
- PWA update failures.

Include backend request/correlation ID in error reports, but never include sensitive response bodies.

---

# 33. Testing Strategy

## 33.1 Unit tests

Test:

- integer-string money parsing;
- IRR/Toman conversion;
- amount formatting;
- Persian/Arabic digit normalization;
- IBAN formatting;
- status mapping;
- permission utilities;
- query-key factories;
- ETag parsing;
- idempotency-key lifecycle;
- normalized crop coordinates;
- privacy-safe telemetry filtering.

## 33.2 Component tests

Required components:

- `AmountInput`;
- `AmountDisplay`;
- `IbanInput`;
- `StatusBadge`;
- `FinancialConfirmDialog`;
- `VersionConflictPanel`;
- `FileUpload`;
- `FileLifecycleBadge`;
- `DocumentPreview`;
- `ManualCropWorkspace`;
- `BatchVersionSummary`;
- `ManagerApprovalView`;
- `EvidenceLinkForm`;
- `PublicationPreview`;
- `PermissionGate`.

## 33.3 API-contract tests

CI must verify:

- generated types match OpenAPI;
- required headers are represented;
- error codes are handled;
- status enum mappings are exhaustive;
- no deprecated endpoint is used.

## 33.4 Integration tests

Use MSW or equivalent for component/application integration tests.

Cover:

- `412 VERSION_CONFLICT`;
- `428 PRECONDITION_REQUIRED`;
- timeout after server commit;
- same idempotency key replay;
- idempotency key reused with different payload;
- session expiry during a form;
- recent authentication;
- file quarantined after upload;
- job partial failure;
- stale approval view.

## 33.5 End-to-end tests

Minimum Phase 1A Playwright scenarios:

1. Trader registration and pending approval.
2. Internal approval of trader.
3. Trader creates beneficiary and payment-request draft with Toman input.
4. Trader submits current request revision.
5. Accountant starts review and marks eligible for batching.
6. Accountant previews split attempts and creates a draft batch version.
7. Accountant finalizes immutable version.
8. Manager reauthenticates and approves exact version/hash.
9. Accountant generates and downloads final export.
10. Accountant marks exact export sent.
11. Accountant uploads a mixed bank-result bundle.
12. Accountant previews a PDF and creates a manual crop.
13. Accountant creates a primary evidence link.
14. Accountant confirms an attempt paid.
15. System blocks overpayment.
16. Accountant previews and creates publication.
17. Trader sees only current safe publication.
18. Trader disputes a result.
19. Evidence/publication correction creates a superseding version.
20. Trader receives correction notification.

## 33.6 Concurrency E2E tests

- two accountants open the same request, one saves first;
- two users try to allocate the same attempt;
- two managers attempt to approve the same version;
- manager opens version N while version N+1 becomes current;
- two accountants try to create different primary evidence links;
- double-click and network timeout do not duplicate a command.

## 33.7 Security tests

- Trader cannot open Admin routes or data;
- Trader cannot download another trader's publication or file;
- mixed bundle never appears in Trader PWA;
- read-only user cannot mutate;
- technical admin lacks financial authority unless explicitly granted;
- signed URL expiry is handled;
- no sensitive data appears in telemetry mocks;
- service worker does not cache financial responses.

## 33.8 Accessibility tests

Use automated checks plus manual keyboard/screen-reader checks for core workflows, especially approval, crop, confirmation, dispute, and file upload.

---

# 34. CI and Quality Gates

Required pipeline steps:

```text
lockfile install
lint
format check
TypeScript typecheck
translation-key validation
unit tests
component tests
API contract generation/check
status mapping exhaustiveness
production builds for both apps
bundle-size checks
Playwright critical workflows
accessibility smoke tests
secret scan
frontend dependency scan
container/static artifact scan where applicable
```

A change must not merge when:

- an API contract changed without regenerated types;
- a status is unmapped;
- a financial command omits idempotency support;
- a mutable edit omits ETag/`If-Match` handling;
- a Trader response component accepts Admin DTOs;
- critical E2E tests fail;
- Persian translation keys are missing for Phase 1A screens.

---

# 35. Implementation Sequence

## 35.1 Foundation

1. Monorepo and two application builds.
2. Shared TypeScript, lint, Tailwind, and test configuration.
3. OpenAPI client generation and error normalization.
4. Authentication/session abstraction.
5. RTL, localization, Jalali, and bidirectional-text foundation.
6. Design tokens and accessible primitives.
7. Money and IBAN components.
8. Query keys, ETag, idempotency, conflict handling.
9. Secure file upload/download primitives.

## 35.2 Trader PWA

1. Login/recovery/pending approval.
2. Shell/navigation/notifications.
3. Beneficiary management.
4. Request draft/revision/submit.
5. Request list/detail/timeline.
6. Gold-sale request and incoming receipt.
7. Publication list/detail/share/acknowledge/dispute.
8. PWA installation and safe update behavior.

## 35.3 Admin operational core

1. Shell and permission-based navigation.
2. Dashboard and work queues.
3. Trader management.
4. Request review and revision comparison.
5. Batch preview/builder/versioning.
6. Manager approval view and recent authentication.
7. Preview/final export and mark-sent workflow.
8. Bank-result upload and workspace.
9. PDF/image preview and Phase 1A manual crop.
10. Matching/evidence link workflows.
11. Payment-result confirmation/retry/correction.
12. Publication preview and correction.
13. Gold-sale, statement-import, incoming-payment, and dispatch screens.
14. Reports, audit, settings, jobs, and retention-governance views.

## 35.4 Optional later phases

- OCR extraction panels;
- automatic segmentation proposals;
- explainable candidate suggestions;
- AI shadow-mode evaluation UI;
- advanced analytics;
- integrations;
- Phase 4 multi-company product UI.

---

# 36. Phase 1A Acceptance Criteria

## 36.1 Architecture

- Two separately built frontend applications exist.
- Trader PWA contains no Admin routes or bundles.
- Shared packages enforce contract reuse without leaking role-specific data.
- Production builds are reproducible from a pinned lockfile.

## 36.2 Financial safety

- Money is never processed as floating point.
- User explicitly chooses IRR or Toman.
- Sensitive commands use one logical idempotency key.
- Mutable edits use server ETag/`If-Match`.
- Version conflicts do not overwrite newer data.
- Financial states are not optimistically finalized.

## 36.3 Request and batch workflow

- Trader creates and submits request revisions.
- Accountant marks a request eligible for batching without manager-request approval.
- Batch preview uses server-calculated attempts.
- Finalized batch version is visibly immutable.
- Manager approves one exact current version and hash.
- Stale approval pages are blocked.
- Preview export is visibly non-sendable.
- Final export integrity and exact mark-sent flow are implemented.

## 36.4 Bank-result and evidence workflow

- Mixed bundles are supported.
- Image and PDF previews work or fail safely.
- Minimal manual crop is available in Phase 1A.
- Crop provenance is submitted correctly.
- Candidate and confirmed evidence are separate.
- One active primary evidence rule is represented and server conflicts are handled.
- Payment confirmation shows aggregate effect and blocks overpayment.

## 36.5 Publication and trader isolation

- Trader sees only authorized immutable publications.
- Mixed bank bundles are never exposed to traders.
- Superseded publications remain historical and are clearly labeled.
- Trader can acknowledge or dispute.
- Material correction creates a new publication and notification.

## 36.6 UX and accessibility

- Production UI is Persian-first and RTL.
- Trader core screens work without horizontal scrolling on common mobile widths.
- Admin core workflows are keyboard-usable.
- Status is not color-only.
- Crop has non-drag controls.
- Error, empty, loading, conflict, and stale states are implemented.

## 36.7 AI independence

- All core workflows work with every AI/OCR flag disabled.
- AI output is labeled as suggestion/extraction only.
- AI technical success never appears as financial confirmation.

---

# 37. Open ADR and Brand Decisions

The following remain external decisions and must not be guessed in implementation:

1. Authentication/session transport.
2. Recent-auth timeout and method.
3. CSRF strategy where applicable.
4. Final Persian font and licensing.
5. Logo and final brand tokens.
6. Default amount-entry unit for each role.
7. Trader-facing IBAN masking.
8. File size limits and production preview renderer limits.
9. Evidence requirement and text-only exception policy.
10. Dual control for correction of a published Paid result.
11. Share-card format and watermark/reference policy.
12. Notification polling interval and future real-time strategy.
13. Saved-filter scope.
14. Final bank-template preview behavior.
15. Production accessibility target and formal audit level.

Fixed decisions that are not open:

- two applications;
- Phase 1A manual crop;
- exact batch-version approval;
- mandatory manager approval for all Phase 1A outgoing batches;
- no offline financial command queue;
- no AI financial authority;
- no Phase 1A multi-company interface.

---

# 38. Coding-Agent Rules

A coding agent must:

1. Use the version 1.1 API and workflow contracts.
2. Keep Trader and Admin applications separate.
3. Never invent statuses or permissions.
4. Never use generic status PATCH forms for financial transitions.
5. Never use JavaScript floating point for money.
6. Preserve entered amount value/unit and canonical IRR.
7. Implement idempotency for critical commands.
8. Implement ETag/`If-Match` for mutable resources.
9. Handle `409`, `412`, and `428` explicitly.
10. Treat finalized batch versions, exports, evidence history, and publications as immutable.
11. Approve exact batch versions, not batch containers.
12. Distinguish Preview Export and Final Export.
13. Mark the exact export sent, not a generic batch.
14. Implement internal manual crop in Phase 1A.
15. Keep crop separate from matching, evidence confirmation, payment confirmation, and publication.
16. Never expose a mixed bank bundle to a trader.
17. Never let AI output perform financial commands.
18. Never store secrets, files, or sensitive API payloads in persistent browser storage.
19. Never queue financial commands offline.
20. Never log sensitive financial content to console or third-party telemetry.
21. Use backend-generated share/publication data.
22. Preserve stale/conflict context instead of silently overwriting it.
23. Keep technical-admin access separate from financial authority.
24. Build accessibility and RTL support into primitives, not as final polish.
25. Update docs, generated API contracts, and tests together when behavior changes.

---

# 39. Final Frontend Position

The frontend is a safety-critical operational layer for high-value gold-trade settlement. Its success is measured by clarity, correctness, controlled speed, privacy, and resistance to repeated-click, stale-data, unit, evidence, and authorization errors.

The Phase 1A milestone is:

> Traders can submit and track requests through a simple Persian mobile experience, while accountants and managers can review, batch, approve, export, reconcile, crop evidence, confirm results, publish safe outcomes, and correct mistakes through a precise and auditable internal web application—without depending on AI, OCR, bank APIs, SMS, or messaging applications.

Later intelligence must enhance these same workflows without replacing human financial authority or creating a separate operational path.
