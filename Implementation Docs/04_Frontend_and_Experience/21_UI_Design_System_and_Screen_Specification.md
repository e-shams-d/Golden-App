# Gold Trade Settlement Platform
# UI Design System and Screen Specification

**Document ID:** `21_UI_Design_System_and_Screen_Specification`  
**Version:** `1.1`  
**Status:** `Authoritative UI Design System and Screen Baseline`  
**Language:** English with Persian/RTL implementation examples  
**Audience:** Product Owner, UI Designer, Frontend Engineer, QA Engineer, Security Reviewer, Coding Agent  
**Primary Purpose:** Define the visual system, component contracts, screen layouts, responsive behavior, financial-safety patterns, and role-specific interface rules for the Trader PWA and Admin Web application.

---

# 0. Document Control

## 0.1 Authority

This document is the primary authority for:

- visual design tokens;
- reusable UI component contracts;
- screen composition;
- role-specific page layouts;
- responsive screen behavior;
- density and information hierarchy;
- visible financial-safety summaries;
- Persian/RTL presentation rules;
- file-preview and manual-crop interface behavior;
- exact batch-version approval presentation;
- evidence, result, and publication interface separation.

This document does not redefine:

- product scope;
- domain invariants;
- database constraints;
- API semantics;
- workflow transitions;
- permissions;
- audit requirements;
- retention policy;
- deployment architecture.

Those topics remain governed by their specialized documents.

## 0.2 Required upstream references

This document must conform to the authoritative v1.1 documents:

1. `00_Master_Implementation_Blueprint.md`
2. `01_Product_Requirements_PRD.md`
3. `02_Domain_Model_and_Business_Rules.md`
4. `03_System_Architecture.md`
5. `04_Database_Schema.md`
6. `05_API_Specification.md`
7. `06_Workflows_and_State_Machines.md`
8. `07_UI_UX_Specification.md`
9. `08_Bank_File_and_Result_Processing.md`
10. `10_Backend_Implementation_Guide.md`
11. `11_Frontend_Implementation_Guide.md`
12. `12_Security_RBAC_Audit.md`
13. `14_Testing_QA_Acceptance.md`
14. `15_Agent_Implementation_Plan.md`
15. `16_Implementation_Documentation_Index.md`
16. `20_Agent_Usage_Instructions.md`

`22_UX_User_Journeys_and_Interaction_Guide.md` remains the primary UX journey reference after its own v1.1 revision. Until then, it must not override this document or any authoritative v1.1 workflow/security rule.

## 0.3 Conflict precedence

When a conflict is found, use this precedence:

1. Security and privacy: document `12`.
2. State transitions and guards: document `06`.
3. Domain meaning and financial invariants: document `02`.
4. API contract and error semantics: document `05`.
5. Bank-processing integrity: document `08`.
6. UI interaction journey: document `22`, once revised.
7. Screen structure and component presentation: this document.
8. Frontend technical implementation: document `11`.
9. High-level UI/UX direction: document `07`.

A visual shortcut may never weaken a financial, security, privacy, or audit rule.

## 0.4 Change summary from version 1.0

Version 1.1:

- makes the internal manual rectangular crop tool mandatory in Phase 1A;
- replaces generic batch approval UI with exact immutable batch-version approval;
- adds content-hash, mapping-version, source-account, and stale-version presentation;
- separates preview export, final export, download, and mark-as-sent UI;
- separates matching candidate, confirmed evidence, payment result, and publication UI;
- introduces immutable publication versions and correction replacement flows;
- introduces ETag, `If-Match`, idempotency, timeout-recovery, and stale-data components;
- formalizes two independent application shells;
- adds luxury-minimal and professional-FinTech design direction;
- adds semantic design tokens, accessibility contracts, and density modes;
- expands gold sale, incoming receipt, statement matching, and dispatch-guard screens;
- removes generic financial CRUD patterns;
- adds explicit coding-agent prohibitions and UI acceptance criteria.

---

# 1. Product UI Positioning

## 1.1 Product character

The interface must communicate:

- trust;
- accuracy;
- financial control;
- operational maturity;
- premium service;
- discretion;
- human accountability.

The desired visual character is:

```text
Luxury Minimalism
+
Professional FinTech
+
High-value Gold Trade Operations
```

The interface must not look like:

- a cryptocurrency trading terminal;
- a black-and-gold casino product;
- a jewellery catalogue;
- a generic spreadsheet clone;
- a messenger application;
- an old accounting desktop application;
- a marketing-heavy consumer finance app;
- a dashboard full of decorative charts.

## 1.2 Guiding implementation phrase

> Preserve the business need and logic, not the limitations or appearance of the current manual tools.

Examples:

```text
messenger approval
→ explicit approval command with actor, exact version, reason, and audit

editable spreadsheet batch
→ immutable ordered batch version with hash and manager approval

shared mixed bank screenshot
→ private source document, controlled crop, privacy review, trader-safe publication
```

## 1.3 Phase 1A visual objective

Phase 1A must feel complete and professional even without OCR, automatic segmentation, native applications, or external integrations.

The manual core must not be visually presented as temporary, unfinished, or inferior.

---

# 2. Fixed UI Architecture Decisions

## 2.1 Two independent client applications

The product has two separate frontend applications:

```text
apps/trader-pwa
apps/admin-web
```

They may share tokens, primitives, generated API types, formatting utilities, and validation schemas, but they must not share route trees or feature bundles.

### Trader PWA

- Persian-first;
- RTL-first;
- mobile-first;
- card-oriented;
- low cognitive load;
- installable PWA;
- safe offline shell only;
- no internal operational details.

### Admin Web

- Persian-first;
- RTL-first;
- desktop-first;
- dense work queues;
- split-pane review;
- keyboard-efficient;
- role-specific navigation;
- no assumption that mobile is the primary operational device.

## 2.2 No hidden shared application

The implementation must not place Admin routes inside the Trader application and merely hide them using permissions, CSS, or navigation rules.

A Trader build must not contain Admin route modules, bank-result workspace modules, or manager approval screens.

## 2.3 Server truth over visual state

The UI never becomes authoritative for:

- financial status;
- approval state;
- paid amount;
- export integrity;
- evidence uniqueness;
- publication activation;
- dispatch eligibility;
- permission decisions.

The UI presents server-authoritative state and sends explicit commands.

---

# 3. Design Token System

## 3.1 Token layers

Use three token layers:

```text
Primitive tokens
→ Semantic tokens
→ Component tokens
```

Primitive values must not be scattered directly through feature components.

## 3.2 Color strategy

Gold is an accent, not the page background and not the dominant text color.

Recommended semantic roles:

| Token | Purpose |
|---|---|
| `surface.canvas` | Main application background |
| `surface.panel` | Cards, drawers, workspaces |
| `surface.subtle` | Secondary grouped content |
| `surface.elevated` | Dialogs, popovers, command panels |
| `text.primary` | Primary readable text |
| `text.secondary` | Supporting information |
| `text.muted` | Metadata and low-emphasis details |
| `border.default` | Standard boundaries |
| `border.strong` | Financial-summary and focus boundaries |
| `accent.gold` | Premium accent, selected details, brand highlight |
| `action.primary` | Main safe command |
| `action.secondary` | Supporting action |
| `state.info` | Informational state |
| `state.success` | Confirmed or complete state |
| `state.warning` | Review, partial, stale, or unusual state |
| `state.danger` | Failed, rejected, blocked, or destructive state |
| `state.neutral` | Draft or inactive state |
| `focus.ring` | Keyboard focus indicator |

Rules:

- never use gold as the only success color;
- never use red for ordinary pending states;
- do not use saturated colors for large page areas;
- do not encode status using color alone;
- maintain accessible contrast for text, icons, and focus rings;
- provide dark-mode readiness only if approved later; Phase 1A may launch with a carefully designed light theme.

## 3.3 Typography

Use a Persian-capable, licensed, web-safe font stack approved for deployment.

Typography roles:

| Role | Usage |
|---|---|
| `display` | Rare page-level emphasis |
| `heading.lg` | Main screen title |
| `heading.md` | Section title |
| `heading.sm` | Card title |
| `body` | Standard content |
| `body.compact` | Dense admin tables |
| `label` | Form and field labels |
| `caption` | Metadata |
| `numeric` | Amounts, references, hashes, IBANs |

Rules:

- use tabular numerals where supported for aligned monetary columns;
- preserve Latin characters for IBAN, UUID, hash, tracking numbers, filenames, and technical identifiers;
- do not render long Persian paragraphs in all-bold text;
- avoid very light font weights for critical financial information;
- do not ship unlicensed font files.

## 3.4 Spacing

Use a consistent spacing scale, for example:

```text
2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64
```

Rules:

- Trader cards use comfortable spacing;
- Admin queues use compact but readable spacing;
- financial confirmation panels receive more separation than ordinary metadata;
- related label/value pairs remain visually grouped;
- dense mode must not reduce touch targets below accessibility requirements.

## 3.5 Radius

Use restrained radii:

- small radius for inputs, chips, and compact controls;
- medium radius for cards and drawers;
- larger radius only for prominent mobile sheets or major empty-state panels.

Avoid excessively rounded “consumer wallet” styling.

## 3.6 Elevation and borders

Prefer subtle borders and low elevation.

Use elevation for:

- modal dialogs;
- command drawers;
- sticky approval summaries;
- popovers;
- mobile bottom sheets.

Do not use heavy shadows on every card.

## 3.7 Motion

Motion must be restrained and functional.

Allowed:

- short state transition;
- drawer opening;
- subtle progress update;
- crop selection feedback;
- success confirmation after server response.

Not allowed:

- celebratory animation for money movement;
- continuous decorative motion;
- motion that hides status changes;
- animation that delays critical confirmation.

Honor `prefers-reduced-motion`.

## 3.8 Density modes

The Admin application supports:

- comfortable density for dashboards and detail pages;
- compact density for accountant queues and data grids.

Density selection must not change meaning, available actions, or security information.

## 3.9 Iconography

Icons must:

- support labels for unfamiliar actions;
- never represent approval or payment using ambiguous decorative symbols;
- use consistent stroke and size;
- include accessible names;
- avoid jewellery or crypto imagery as general navigation metaphors.

## 3.10 Z-index layers

Define a controlled layer scale for:

1. page content;
2. sticky headers;
3. dropdowns/popovers;
4. drawers;
5. dialogs;
6. urgent system overlays.

Do not assign arbitrary high z-index values inside features.

---

# 4. RTL, Bidi, Number, Date, and Identifier Rules

## 4.1 Direction

The page direction is RTL.

Use LTR isolation for:

- IBAN;
- tracking number;
- UUID;
- SHA-256 hash;
- filename extension;
- API request ID;
- version number;
- technical timestamp where displayed.

Use CSS bidi isolation rather than inserting invisible characters manually.

## 4.2 Persian and Latin digits

Input components must normalize Persian, Arabic, and Latin digits consistently.

Display policy may use Persian digits for ordinary dates and counts, while preserving Latin digits for identifiers where copying and external matching are important.

## 4.3 Money storage and display

Canonical money is integer IRR.

The UI must preserve and display:

- original entered value;
- original entered unit;
- canonical IRR value;
- Toman equivalent where useful.

Example:

```text
مبلغ واردشده: ۱۲۵٬۰۰۰٬۰۰۰ تومان
مبلغ ثبت‌شده: ۱٬۲۵۰٬۰۰۰٬۰۰۰ ریال
```

Never infer the unit from magnitude.

Never calculate canonical money using JavaScript floating-point.

## 4.4 Money input

The user must explicitly select:

```text
تومان | ریال
```

The component must:

- accept integer input only;
- normalize digits and separators;
- show exact converted value;
- warn about unusual magnitude without blocking valid values;
- present a confirmation summary before sensitive submission;
- preserve the original unit after submission;
- support string/BigInt-safe calculations.

## 4.5 Date and time

The server stores canonical UTC timestamps.

The UI may show Jalali date and local time, but must:

- preserve exact server timestamp for audit detail;
- show timezone where ambiguity matters;
- avoid parsing locale-formatted dates as business truth;
- show “relative time” only as secondary information.

Example:

```text
۱۴۰۵/۰۲/۰۶، ساعت ۱۳:۴۵
زمان دقیق سامانه: 2026-04-26T10:15:00Z
```

## 4.6 IBAN presentation

IBAN must:

- remain LTR;
- preserve leading characters and zeros;
- support copy;
- use grouping for readability without changing stored value;
- be masked in contexts governed by privacy policy;
- never be truncated without an expand or copy mechanism on operational screens.

## 4.7 Hash presentation

Content hash and checksum components show:

- a shortened fingerprint by default;
- a copy action;
- full value in an accessible detail view;
- match/mismatch state;
- no assumption that users can manually verify the full value.

---

# 5. Accessibility Baseline

Target WCAG 2.1 AA unless a later ADR adopts a newer formal target.

## 5.1 Keyboard

All Admin workflows must be keyboard-operable.

Requirements:

- visible focus;
- logical RTL tab order;
- no keyboard trap;
- shortcut hints where supported;
- Escape closes non-destructive overlays;
- Enter never triggers a sensitive financial command without an explicit confirmation step;
- table rows and command menus remain reachable.

## 5.2 Screen readers

Expose:

- field labels;
- units;
- full status text;
- warning severity;
- progress amounts;
- selected crop coordinates through numeric fields;
- dialog purpose;
- before/after correction summaries.

Do not announce “green” or “red” as the status meaning.

## 5.3 Touch targets

Trader PWA primary actions and mobile crop controls must meet minimum touch-target sizing.

## 5.4 Contrast

Focus, status, disabled, selected, and warning states must remain distinguishable under contrast requirements.

## 5.5 Crop accessibility

The crop tool must not depend only on drag gestures.

Provide:

- numeric x/y/width/height fields;
- keyboard adjustment;
- reset;
- fit-to-page;
- zoom controls;
- screen-reader labels;
- clear source page and rotation context.

---

# 6. Global Application Shells

## 6.1 Trader PWA shell

```text
Top app bar
  page title
  connection indicator when offline
  safe notification indicator
  profile/status shortcut

Main content
  action cards
  request/result lists
  forms
  publication views

Bottom navigation
  dashboard
  gold
  payments
  results
  profile
```

Rules:

- primary create action is reachable by thumb;
- no internal Admin vocabulary;
- no raw database IDs;
- no mixed bank-document previews;
- no audit drawer;
- no queue density intended for accountant work.

## 6.2 Admin Web shell

```text
Header
  center name
  environment badge
  role context
  global task/alert access
  user/session menu

Sidebar
  dashboard
  work queues
  traders
  beneficiaries as permitted
  gold sales
  payment requests
  payment batches
  bank results
  incoming statements
  reports
  configuration
  audit/security where permitted

Main workspace
  queue/list/detail
  split review panels
  sticky command summary
  drawers and dialogs
```

## 6.3 Role-aware navigation

Navigation is generated from server-authoritative permissions, but hidden navigation is not a security control.

### Accountant

Primary navigation:

- work queue;
- payment requests;
- batches;
- bank results;
- evidence and results;
- incoming payments;
- operational reports.

### Manager

Primary navigation:

- manager dashboard;
- exact-version approval queue;
- sensitive correction queue;
- reports and warnings.

### Warehouse operator

Primary navigation:

- ready-for-dispatch queue;
- dispatch registration;
- receipt confirmation.

### Technical admin

Primary navigation:

- job failures;
- storage health;
- configuration technical views;
- system information.

Technical admin navigation must not imply financial authority.

### Read-only auditor

Primary navigation:

- permitted reports;
- audit views;
- immutable history;
- no command controls.

## 6.4 Environment banner

Development, staging, pilot, and production channels must be visually distinguishable.

Staging/pilot must show a persistent environment label.

Production must not display test wording, but may show release version in system information.

---

# 7. Global UI States

Every screen must implement:

- loading;
- partial loading;
- empty state;
- permission denied;
- not found;
- validation error;
- workflow rejection;
- stale version;
- missing precondition;
- idempotency conflict;
- timeout with uncertain outcome;
- background processing;
- processing failure;
- file quarantined;
- export integrity mismatch;
- maintenance/read-only mode;
- session expired;
- recent-auth required.

## 7.1 Loading

Use skeletons only when the final structure is known.

Never show a misleading zero total while data is loading.

## 7.2 Empty state

An empty state must explain:

- what the list represents;
- why it may be empty;
- the safe next action;
- whether filters are active.

## 7.3 Permission denied

Do not reveal sensitive entity existence unnecessarily.

## 7.4 Workflow rejection

Show:

- what command was rejected;
- current authoritative status;
- required next condition;
- request/correlation ID;
- safe navigation option.

## 7.5 Stale version

For `412 VERSION_CONFLICT`, show a dedicated conflict panel:

```text
این اطلاعات پس از بازشدن صفحه تغییر کرده است.
نسخه فعلی را دوباره دریافت و تغییرات را بررسی کنید.
```

Never silently re-submit a financial command against a new version.

## 7.6 Missing precondition

For `428 PRECONDITION_REQUIRED`, explain that the page or client is missing the required version context and must refresh.

## 7.7 Idempotency conflict

For reused key with a different payload, do not suggest blind retry.

## 7.8 Timeout after submit

Show:

```text
در حال بررسی نتیجه عملیات…
لطفاً دوباره دکمه را فشار ندهید.
```

The client must query/reconcile using the same logical command context.

---

# 8. Reusable Component Contracts

## 8.1 `PageHeader`

Contains:

- title;
- subtitle/context;
- primary status;
- key reference;
- role-safe actions;
- breadcrumb where useful.

## 8.2 `EntitySummaryCard`

Presents immutable identity and current status for a domain entity.

Must not contain editable fields disguised as plain text.

## 8.3 `FinancialAmountInput`

Props/contract:

- `enteredValue: string`;
- `enteredUnit: IRR | TOMAN`;
- `canonicalIrr: string`;
- validation state;
- configured warnings;
- read-only mode;
- original-unit preservation.

Must not emit JavaScript `number` for canonical value.

## 8.4 `MoneyDisplay`

Displays:

- canonical IRR;
- optional Toman equivalent;
- original entered unit/value when relevant;
- sign and direction;
- accessible full phrase.

## 8.5 `IBANField`

Supports:

- normalized display;
- validation state;
- copy;
- mask mode;
- snapshot label;
- difference highlighting between revisions.

## 8.6 `StatusBadge`

Uses exact API status values and exhaustive mapping.

Unknown statuses must fail visibly in development and appear as “unsupported status” in production, not as a generic success state.

## 8.7 `VersionBadge`

Shows:

- version number;
- current/superseded state;
- immutable/draft state;
- stale indicator.

Used for:

- request revisions;
- batch versions;
- bank mappings;
- publications;
- import runs.

## 8.8 `WorkflowTimeline`

Shows authoritative events, not inferred milestones.

May include:

- actor;
- timestamp;
- command;
- version/reference;
- result;
- reason.

## 8.9 `CommandButton`

Sensitive command buttons must support:

- server permission state;
- loading state;
- idempotency context;
- disabled reason;
- confirmation workflow;
- uncertain-outcome state;
- no optimistic financial status update.

## 8.10 `ConfirmationDialog`

Required fields vary by command, but the dialog must show the exact target.

For financial commands, show:

- action name;
- entity/reference;
- exact version;
- amount;
- count/row count;
- bank/source account where relevant;
- material warnings;
- reason/note requirement;
- recent-auth requirement;
- audit statement.

## 8.11 `RecentAuthenticationDialog`

Reauthentication is a separate security step.

It does not submit the financial command automatically unless the user clearly confirms the command afterward within the valid context.

## 8.12 `ConflictBanner`

Shows:

- local version;
- server version;
- change time/actor if available;
- refresh action;
- safe copy of unsaved non-financial form values where allowed.

It must not offer automatic merge for financial fields.

## 8.13 `RequestIdErrorPanel`

Shows a user-safe error plus copyable request/correlation ID.

Never expose stack traces.

## 8.14 `WorkQueueTable`

Supports:

- server pagination;
- server filtering;
- saved views if approved;
- dense rows;
- keyboard navigation;
- sticky column headers;
- clear next action;
- role-safe columns;
- no hidden meaning in row color.

Default columns:

- reference;
- subject/trader;
- amount;
- status;
- age;
- warning count;
- owner/assignee where supported;
- next action.

## 8.15 `FilterBar`

Filters must be explicit and removable.

Show active-filter count.

Do not apply high-impact filters invisibly from previous sessions without indicating them.

## 8.16 `DataGrid`

For dense Admin pages:

- column definitions are domain-specific;
- raw database columns are not exposed automatically;
- row selection must be distinguishable from command execution;
- bulk actions require explicit preview;
- totals are server-derived for financial actions.

## 8.17 `FileUploadPanel`

Supports:

- staged upload;
- progress;
- cancel before finalization;
- allowed type/size guidance;
- checksum/processing state;
- quarantined state;
- retry;
- no public storage path.

## 8.18 `SecureFileViewer`

Supports:

- authorized short-lived access;
- image/PDF page view;
- zoom;
- pan;
- rotate;
- page thumbnails;
- processing state;
- expired access recovery;
- no browser cache assumption for sensitive files.

## 8.19 `ManualCropWorkspace`

Mandatory Phase 1A component.

Layout:

```text
Left or center:
  source file/page viewer
  zoom/pan/rotation
  rectangular selection

Right panel:
  selected page
  normalized x/y/width/height
  crop preview
  source dimensions
  renderer status
  privacy checklist
  save/retry actions
```

The component sends decimal-string normalized coordinates.

Creating a crop creates a `ReceiptSegment`; it does not confirm evidence, mark payment paid, or publish to the trader.

## 8.20 `EvidencePreviewCard`

Shows:

- evidence category;
- source type;
- primary/supplementary state;
- active/replaced/revoked state;
- linked attempt;
- privacy approval;
- checksum/reference;
- publication impact.

## 8.21 `MatchingCandidateCard`

Shows explainable matching features:

- amount comparison;
- IBAN comparison;
- beneficiary comparison;
- bank/batch context;
- date/time comparison;
- warnings.

Do not label the score as probability that payment is paid or verified.

Accepting a candidate moves it to confirmation review only.

## 8.22 `PaymentResultConfirmationPanel`

Before confirming paid/failed, show:

- exact attempt;
- request revision;
- attempt amount;
- current paid total;
- resulting paid total;
- remaining amount;
- expected request status;
- beneficiary snapshot;
- IBAN snapshot;
- active evidence;
- overpayment block;
- exception policy if enabled.

## 8.23 `PublicationPreview`

Shows exactly what the trader will see.

Must exclude:

- internal notes;
- unrelated bank transactions;
- full bundle pages;
- candidate scores;
- audit metadata;
- unmasked private fields beyond policy.

## 8.24 `PublicationVersionCard`

Shows:

- publication version;
- active/superseded/revoked state;
- published time;
- publishing actor;
- reason for replacement;
- trader acknowledgement/dispute state.

## 8.25 `AuditDrawer`

Available only to authorized Admin roles.

Shows:

- event;
- actor;
- assurance/recent-auth context where permitted;
- timestamp;
- entity version/hash reference;
- before/after summary;
- reason;
- request ID.

## 8.26 `IntegrityStatePanel`

Used for final exports and important files.

Shows checks:

- exact batch version;
- content hash;
- approval hash;
- row count;
- total;
- mapping version;
- source account;
- file checksum.

Mismatch state must block send-related actions.

## 8.27 `ProgressAmount`

Used for partial payments and incoming settlement.

Shows:

- target;
- confirmed amount;
- remaining amount;
- percentage only as secondary information;
- no rounded financial totals.

## 8.28 `SensitiveCorrectionComparison`

Shows before/after for:

- evidence;
- paid result;
- publication;
- beneficiary or IBAN revision;
- bank mapping where relevant.

Requires reason and impact summary.

---

# 9. Trader PWA Screens

## 9.1 Login and registration

Screens:

- login;
- registration;
- verification step according to auth ADR;
- pending approval;
- rejected registration;
- suspended account;
- session expired.

Do not reveal internal approval queues or reviewer identity.

## 9.2 Trader dashboard

Primary content:

- payment requests needing trader action;
- latest published results;
- active gold orders;
- disputes or corrections requiring attention;
- create request action.

Avoid decorative financial charts in Phase 1A.

## 9.3 Beneficiary list

Shows reusable beneficiary records.

Each item includes:

- name;
- masked or full IBAN according to context;
- status/validation warnings;
- last used date;
- edit availability.

Changing beneficiary data does not rewrite previous request snapshots.

## 9.4 Beneficiary create/edit

Fields:

- beneficiary name;
- destination IBAN;
- optional national ID;
- optional description.

The form must explain that requests preserve a snapshot of the selected beneficiary.

## 9.5 Create payment request

Sections:

1. beneficiary selection or creation;
2. amount and explicit unit;
3. description;
4. optional allowed attachments;
5. review summary;
6. save draft or submit.

Review summary shows:

- entered value/unit;
- canonical IRR;
- beneficiary;
- IBAN;
- warnings;
- statement that submitted financial fields require a new revision to correct.

## 9.6 Payment request list

Use filters or grouped sections based on exact statuses, not outdated broad tabs.

Recommended user-facing groups:

- drafts;
- needs my correction;
- under center review;
- being prepared/processed;
- partially paid;
- completed;
- failed/retry/dispute;
- closed.

Each item shows attempt count and publication availability.

## 9.7 Payment request detail

Sections:

- current request revision;
- original amount/unit;
- beneficiary snapshot;
- status;
- attempt summary;
- publication history visible to trader;
- trader actions.

Trader actions may include:

- edit draft;
- create correction revision when requested;
- acknowledge publication;
- dispute publication;
- download/share publication-safe artifact.

## 9.8 Trader correction screen

Shows:

- center correction reason;
- current revision;
- editable fields;
- before/after preview;
- new revision number.

It must not overwrite the prior revision.

## 9.9 Payment result/publication screen

The screen is based on `PaymentResultPublication`, not raw mutable attempt data.

Shows:

- publication version;
- paid/failed summary;
- attempt breakdown if relevant;
- beneficiary;
- masked IBAN;
- safe evidence;
- publication time;
- current/superseded indicator;
- acknowledgement/dispute actions;
- share/download action.

## 9.10 Publication history

Superseded versions remain viewable if policy permits, with a clear “replaced” label and no ambiguity about the current version.

## 9.11 Trader dispute screen

Requires:

- publication version;
- issue category;
- explanation;
- optional allowed attachment;
- acknowledgement that dispute does not automatically reverse a bank payment.

## 9.12 Gold order screens

Screens:

- create order/request;
- price offer/version detail;
- incoming payment instructions;
- incoming receipt upload;
- settlement progress;
- dispatch status;
- receipt acknowledgement.

The UI must distinguish:

- requested weight;
- priced weight/value;
- incoming payment confirmed;
- physical settlement;
- offset settlement;
- dispatch eligibility.

## 9.13 Trader profile

Shows:

- profile;
- account status;
- session/logout;
- language/accessibility preferences;
- support path.

No internal risk flags or audit trail.

---

# 10. Admin Shared Screens

## 10.1 Admin login

Supports:

- secure authentication;
- recent-auth path;
- session-expiry handling;
- non-disclosing login errors;
- environment indication.

## 10.2 Admin dashboard

Dashboard content must be role-specific.

Shared elements:

- work requiring action;
- financial totals for relevant period;
- warning counts;
- failed jobs or file issues where permitted;
- links to actionable queues.

Do not show data the role cannot open.

## 10.3 Global work queue

Queue types may include:

- new payment requests;
- corrections returned by trader;
- requests eligible for batching;
- batch versions awaiting approval;
- final exports awaiting generation or send recording;
- bank-result bundles awaiting review;
- attempts awaiting evidence or result;
- retries;
- overpayment reconciliation;
- publication corrections;
- incoming receipt review;
- dispatch tasks;
- job/file failures.

## 10.4 Trader management

Screens:

- trader list;
- trader detail;
- approval/rejection;
- suspension/reactivation;
- permitted internal notes;
- related operational history.

Technical admin does not automatically receive access to all trader financial detail.

## 10.5 Audit and security event views

Separate:

- business audit events;
- security events;
- file-access events where policy permits.

Audit screens are read-only.

---

# 11. Accountant Payment Request Screens

## 11.1 Request review queue

Default columns:

- request reference;
- trader;
- current revision;
- entered amount/unit;
- canonical IRR;
- beneficiary;
- IBAN warning;
- submitted time;
- status;
- next action.

## 11.2 Request review workspace

Recommended split layout:

```text
Main panel:
  request revision
  beneficiary snapshot
  amount
  attachments
  validation warnings
  revision history

Side command panel:
  mark under review
  request trader correction
  mark eligible for batching
  cancel when permitted
```

The accountant does not perform manager approval at request level.

## 11.3 Request correction command

Dialog requires:

- exact request version;
- correction reason;
- fields requiring correction;
- trader-visible message;
- internal note if permitted.

## 11.4 Mark eligible for batching

Show:

- exact revision;
- amount;
- beneficiary snapshot;
- configured warnings;
- statement that this is operational eligibility, not manager approval.

---

# 12. Batch Builder and Batch Version Screens

## 12.1 Eligible request selection

The screen supports:

- filtering;
- server-side selection;
- exact selected revision display;
- total preview;
- duplicate/warning display;
- source bank profile and source account context.

## 12.2 Server preview

Before creating a draft version, request a server preview.

Display:

- source requests/revisions;
- generated attempts;
- split reason;
- ordered rows;
- totals;
- row count;
- warnings;
- excluded items and reasons.

Frontend-calculated totals are secondary verification only.

## 12.3 Draft batch version

Shows:

- logical batch reference;
- draft version number;
- bank profile version;
- mapping version;
- source account;
- ordered items;
- totals;
- validation state;
- edit controls.

## 12.4 Finalize batch version

Confirmation shows:

- exact ordered rows;
- total IRR;
- row count;
- request/trader/beneficiary counts;
- bank profile version;
- mapping version;
- source account;
- warnings;
- statement that the version becomes immutable.

After success, show the server-generated content hash.

## 12.5 Replacement version

The UI must not edit a finalized version.

Use:

```text
Create replacement version
```

Show differences between old and new versions and the reason for replacement.

## 12.6 Batch detail

Sections:

- logical batch summary;
- current version;
- all version history;
- approval history;
- export history;
- send history;
- result bundle associations;
- audit.

---

# 13. Manager Exact-Version Approval Screens

## 13.1 Manager dashboard

Shows:

- versions awaiting approval;
- total value awaiting approval;
- warning count;
- age of oldest item;
- sensitive corrections awaiting review.

## 13.2 Approval queue

Each row must identify the exact version, not only the logical batch.

Columns:

- batch reference;
- version;
- total;
- row count;
- bank;
- source account;
- mapping version;
- warning count;
- prepared/finalized by;
- age.

## 13.3 Approval detail

Mandatory visible information:

- batch reference;
- exact version;
- immutable status;
- total IRR and Toman equivalent;
- request count;
- attempt/row count;
- trader count;
- beneficiary count;
- bank profile version;
- mapping version;
- source account;
- content hash fingerprint;
- ordered rows;
- warnings;
- non-sendable preview export if available;
- finalizer identity;
- separation-of-duty status.

## 13.4 Stale approval protection

If the page version is no longer current:

- block approve/reject command;
- show a prominent stale banner;
- provide link to current version;
- retain the old page as read-only history;
- do not transfer the open dialog to the new version.

## 13.5 Approve command

Requires:

- recent authentication;
- exact version ID;
- expected content hash;
- current version precondition;
- explicit confirmation.

The UI updates only after authoritative server success.

## 13.6 Reject command

Requires reason.

Rejection does not edit the version; a new replacement version may be created later.

---

# 14. Bank Export Screens

## 14.1 Preview export

Preview may exist before approval for review.

It must have a persistent watermark/banner:

```text
PREVIEW — NOT APPROVED FOR BANK SUBMISSION
```

It must not offer:

- mark as sent;
- official checksum as final;
- send-ready status.

## 14.2 Final export generation

Generation screen identifies:

- exact approved batch version;
- approval reference;
- content hash;
- bank profile version;
- mapping version;
- source account;
- expected row count and total.

## 14.3 Export processing states

- requested;
- generating;
- ready;
- quarantined;
- failed;
- superseded if policy applies.

## 14.4 Final export detail

Shows:

- file name;
- checksum;
- generator version;
- generation time;
- exact version;
- approval/hash match;
- row count;
- total;
- mapping;
- source account;
- integrity state;
- download history where permitted.

## 14.5 Integrity mismatch

When quarantined:

- block download for bank submission;
- block mark-as-sent;
- show each failed check;
- create/link urgent review task;
- no “download anyway” option.

## 14.6 Download

The UI must clearly state:

```text
Downloading the file does not mean it was sent to the bank.
```

## 14.7 Mark exact export as sent

Confirmation shows:

- export reference;
- filename;
- batch/version;
- checksum/integrity state;
- row count;
- total;
- bank/source account;
- submission channel;
- sent time;
- note.

The command targets the exact export.

---

# 15. Bank Result Bundle and Manual Processing Screens

## 15.1 Bundle upload

Fields:

- bank profile/version context;
- source/received time;
- optional related batch/export references;
- one or more files;
- note.

Rules:

- bundle may contain multiple files;
- bundle may contain multiple batches/traders;
- original files remain private;
- upload enters file lifecycle processing.

## 15.2 Bundle list

Columns:

- bundle reference;
- bank;
- received time;
- file count;
- processing state;
- unresolved item count;
- reviewer;
- warning count.

## 15.3 Bundle workspace

Recommended desktop layout:

```text
Top bar:
  bundle context
  file and unresolved-item navigation
  processing status

Left/center:
  secure image/PDF viewer
  page thumbnails
  zoom/pan/rotation
  crop overlay

Right:
  selected receipt segment
  attempt search/context
  candidate comparison
  evidence confirmation
  result confirmation

Bottom drawer:
  history
  audit
  jobs
  unresolved items
```

## 15.4 Manual crop flow

Steps:

1. select authorized source file;
2. select page;
3. rotate if required;
4. draw rectangle or use numeric fields;
5. inspect normalized coordinates;
6. render preview;
7. complete privacy checklist;
8. save `ReceiptSegment`;
9. wait for derived-file processing;
10. proceed to candidate/evidence review separately.

## 15.5 Crop privacy checklist

The reviewer confirms:

- no unrelated transaction is visible;
- no unrelated beneficiary/IBAN is visible;
- crop corresponds to the selected attempt context;
- content is readable;
- source and page are correct.

## 15.6 Crop failure

Show:

- failure reason safe for user;
- retry action;
- renderer/version reference;
- external evidence upload fallback;
- no active evidence state.

## 15.7 External evidence fallback

The accountant may upload an already-prepared crop or structured result where policy permits.

The UI must label the source as external/manual and preserve provenance.

---

# 16. Candidate, Evidence, Result, and Publication Screens

## 16.1 Matching candidate review

Candidate acceptance means:

```text
selected for evidence/result confirmation review
```

It does not mean:

- evidence confirmed;
- payment paid;
- result published.

## 16.2 Confirmed evidence link

The screen allows the authorized reviewer to:

- choose attempt;
- choose segment/file;
- mark primary or supplementary;
- confirm relationship;
- provide reason;
- see uniqueness conflict.

## 16.3 Evidence replacement

Do not delete existing evidence.

Show:

- old evidence;
- new evidence;
- reason;
- primary-state transition;
- publication impact;
- trader notification impact;
- required sensitive review.

## 16.4 Confirm attempt paid

Display the full aggregate effect.

If resulting total exceeds request amount:

- block command;
- display excess amount;
- create reconciliation path;
- do not provide “confirm anyway”.

## 16.5 Confirm attempt failed

Show:

- exact attempt;
- failure reason;
- retry eligibility;
- remaining amount;
- impact on parent request.

## 16.6 Retry creation

Shows:

- failed attempt;
- previous request revision;
- current request revision;
- snapshot differences;
- remaining amount;
- new attempt amount;
- statement that a new batch version and manager approval are required.

Beneficiary/IBAN are changed through request revision, not inside the retry dialog.

## 16.7 Publication preview

The accountant previews the trader-visible snapshot.

The preview must be visually distinct from the published version.

## 16.8 Publish result

Confirmation shows:

- publication version to be created;
- request and attempts included;
- safe evidence;
- masked fields;
- trader notification;
- immutable snapshot statement.

## 16.9 Published result correction

Flow:

```text
open current publication
→ prepare correction
→ compare before/after
→ manager/second reviewer when required
→ create replacement publication
→ supersede old version
→ notify trader
```

No in-place edit.

---

# 17. Gold Sale, Incoming Payment, and Dispatch Screens

## 17.1 Gold order queue

Columns:

- order reference;
- trader;
- requested weight/type;
- pricing status/version;
- incoming confirmed amount;
- settlement method;
- dispatch eligibility;
- age/warnings.

## 17.2 Pricing workspace

Shows:

- request details;
- pricing version;
- unit price;
- total IRR;
- validity period;
- reason/notes;
- acceptance state.

Pricing changes create a new version where required.

## 17.3 Incoming receipt upload/review

Supports:

- private file upload;
- amount/unit;
- payer context;
- bank/reference;
- review state;
- statement-row matching.

## 17.4 Statement import preview

Shows:

- import run version;
- source file;
- rows parsed;
- duplicates;
- invalid rows;
- proposed normalized values;
- partial import selection;
- no automatic overwrite of prior import run.

## 17.5 Incoming match review

Separates candidate match from confirmed incoming payment.

## 17.6 Dispatch guard panel

Before dispatch, show:

- order/pricing version;
- required settlement amount;
- confirmed incoming amount;
- remaining amount;
- physical/offset settlement state;
- holds or warnings;
- dispatch permission.

The Warehouse role cannot override financial settlement rules.

## 17.7 Dispatch registration

Requires:

- exact order/version;
- weight/item details;
- operator;
- time;
- recipient/hand-off evidence where required;
- confirmation.

---

# 18. Settings and Administration Screens

## 18.1 Bank profile and mapping

Separate screens for:

- bank profile;
- bank profile versions;
- source accounts;
- export mappings;
- statement mappings;
- templates;
- split rules.

Used versions become immutable; changes create new versions.

## 18.2 Role and permission management

Display explicit permission catalogue.

Do not present a permanent unrestricted `super_admin` as normal configuration.

## 18.3 Feature flags

Feature flags may control optional capabilities such as AI provider use.

They may not disable:

- manager approval;
- audit;
- ownership checks;
- file authorization;
- retention/legal-hold safeguards.

## 18.4 Retention and legal hold

Retention is a governed workflow, not a simple “days” input.

Screens may include:

- policy proposal;
- dry-run preview;
- affected object counts;
- legal-hold conflicts;
- approval state;
- execution result.

## 18.5 Job and storage operations

Technical screens show:

- failed jobs;
- outbox age;
- storage reconciliation findings;
- quarantined files;
- retry actions.

They do not grant financial confirmation authority.

---

# 19. Responsive Behavior

## 19.1 Trader PWA

Breakpoints must preserve:

- readable amount;
- accessible primary actions;
- status visibility;
- safe file upload;
- publication view;
- no horizontal overflow for IBAN.

## 19.2 Admin Web

Desktop is primary.

Tablet fallback may stack split panes.

On small screens:

- critical review panels become sequential;
- sticky summary remains accessible;
- dense tables may become cards or horizontally scroll with explicit column priorities;
- manager approval still shows all exact-version facts before command.

Do not remove critical context merely to fit a narrow screen.

## 19.3 Manual crop mobile support

Phase 1A must support at least the approved operational device matrix.

Desktop/tablet is preferred for mixed bank-result review.

If mobile crop is supported, provide both gesture and numeric controls.

---

# 20. Security and Privacy Presentation Rules

## 20.1 Frontend visibility is not authorization

All commands are server-authorized.

## 20.2 Sensitive data minimization

Do not show full IBAN, national ID, or internal notes where the task does not require it.

## 20.3 Files

- no public paths;
- no permanent signed URLs;
- no mixed bundle to trader;
- no sensitive browser caching;
- revoke viewer access after session expiry;
- clean object URLs when previews close.

## 20.4 Technical admin

Technical admin interfaces must avoid broad financial data exposure and must not include hidden financial command buttons.

## 20.5 Screenshot and share safety

Only publication-safe artifacts are designed for sharing.

Operational screens should avoid encouraging screenshots of mixed or sensitive data.

---

# 21. Error and Recovery Patterns

## 21.1 `401 SESSION_EXPIRED`

- clear sensitive client cache;
- navigate to login;
- preserve safe return path only;
- do not replay financial command automatically.

## 21.2 `403 FORBIDDEN`

- show role-safe explanation;
- do not reveal hidden records;
- provide support/request ID path.

## 21.3 `409`

Possible UI categories:

- idempotency key reused with different payload;
- uniqueness conflict;
- active evidence conflict;
- already-processed command.

## 21.4 `412 VERSION_CONFLICT`

Use conflict banner and explicit refresh.

## 21.5 `428 PRECONDITION_REQUIRED`

Require page reload/client update.

## 21.6 `503`

Distinguish:

- service unavailable;
- background processing unavailable;
- optional AI unavailable.

Manual Phase 1A workflow must remain available when AI is unavailable.

## 21.7 Upload interruption

Show whether:

- upload never completed;
- object exists but metadata finalization failed;
- file is quarantined;
- retry should reuse existing upload context or start a new upload.

---

# 22. Notifications and Task Indicators

Phase 1A may use polling or server-supported refresh.

Notifications must:

- contain minimal sensitive data;
- link to authorized screens;
- show read/unread state;
- not be a substitute for work queues;
- not imply completion before server confirmation.

Urgent alerts include:

- export integrity mismatch;
- overpayment reconciliation;
- stale approval attempt;
- file quarantine;
- wrong publication correction task.

---

# 23. Analytics and Telemetry Boundaries

Allowed UX metrics:

- queue age;
- time to complete a workflow step;
- error category;
- feature adoption;
- page performance;
- command success/failure count without sensitive values.

Do not send:

- amount as telemetry label;
- IBAN;
- beneficiary name;
- file content;
- OCR text;
- tracking number;
- raw API payload;
- publication evidence.

---

# 24. Phase 1A UI Scope

## 24.1 Required

Phase 1A UI must include:

- independent Trader PWA and Admin Web shells;
- authentication/session-expiry/recent-auth surfaces;
- trader registration and approval states;
- beneficiary management;
- payment request draft, submit, revision, correction, list, and detail;
- accountant request review and eligible-for-batching command;
- server batch preview;
- immutable batch-version creation/finalization/replacement;
- exact manager approval/rejection;
- preview export and final export screens;
- export integrity and exact mark-as-sent flow;
- bank-result bundle upload and review workspace;
- secure PDF/image viewer;
- internal manual rectangular crop;
- external evidence fallback;
- candidate review;
- confirmed evidence link;
- paid/failed confirmation;
- partial payment and retry;
- overpayment reconciliation block;
- publication preview, publish, acknowledge, dispute, and replacement version;
- gold sale, incoming receipt, statement preview/matching, and dispatch guard;
- work queues, reports, audit views, job/file failure screens;
- all standard error, stale-version, idempotency, and timeout recovery states.

## 24.2 Not required in Phase 1A

- OCR extraction;
- automatic segmentation;
- automatic candidate generation;
- AI confidence overlays;
- bank API integration;
- native Android/Windows applications;
- internal chat;
- real-time collaborative editing;
- advanced risk dashboards;
- multi-company tenant selector;
- subscription/billing UI.

---

# 25. UI Acceptance Criteria

The UI baseline is accepted only when:

1. Trader and Admin applications are independently built and deployed.
2. Persian/RTL layout is correct across supported screens.
3. Money cannot be confused between IRR and Toman.
4. JavaScript floating-point is not used for canonical financial values.
5. Trader request correction creates a visible new revision.
6. Accountant eligibility is not presented as manager approval.
7. Manager sees and approves an exact immutable batch version and hash.
8. A stale approval page cannot approve a newer version.
9. Preview export is visibly non-sendable.
10. Final export integrity failure blocks download/send actions.
11. Download is not presented as bank submission.
12. Manual rectangular crop works without OCR.
13. Crop creation does not mark payment paid or publish a result.
14. Candidate acceptance is visibly separate from evidence confirmation.
15. Evidence confirmation is visibly separate from paid/failed result confirmation.
16. Overpayment is blocked without a normal override.
17. Trader sees only an immutable publication-safe result.
18. Published corrections create a replacement publication version.
19. ETag conflict, missing precondition, idempotency conflict, and timeout-after-submit have dedicated UI behavior.
20. No trader can access another trader's data or a full mixed bank bundle.
21. Keyboard and screen-reader tests pass for critical Admin workflows.
22. Sensitive files and financial API responses are not stored in offline caches.
23. Technical admin has no implicit financial command UI.
24. All critical screen states have automated or manual acceptance coverage in document `14`.

---

# 26. Suggested UI Implementation Order

1. Semantic design tokens and Persian typography integration.
2. Shared RTL, bidi, money, date, IBAN, status, and error primitives.
3. Typed API client integration, ETag, idempotency, and session handling.
4. Independent Trader and Admin shells.
5. Authentication, pending approval, permission-denied, and recent-auth surfaces.
6. Trader beneficiary and payment-request revision flows.
7. Accountant request queues and review workspace.
8. Batch preview, version builder, finalize, replacement, and detail.
9. Manager exact-version approval and stale-page protection.
10. Preview/final export, integrity, download, and mark-sent flows.
11. Bank-result upload, secure viewer, manual crop, and external evidence fallback.
12. Candidate, evidence, result, retry, reconciliation, and publication flows.
13. Gold sale, incoming statement, settlement, and dispatch screens.
14. Audit, reports, settings, retention, and technical operations screens.
15. Accessibility, responsive refinement, visual regression, and hardening.

---

# 27. Open Decisions Requiring ADR or Product Approval

- final brand name and logo;
- final light-theme palette and whether dark mode is supported;
- Persian font and licensing/distribution method;
- default amount-entry unit;
- exact IBAN masking rules by screen and role;
- formal accessibility conformance target;
- supported browsers and devices;
- mobile crop support level;
- recent-auth timeout and visual flow;
- text-only payment-result exception policy;
- dual-control policy for published paid-result corrections;
- share-card format and fields;
- notification refresh mechanism;
- analytics/error-monitoring provider;
- date library and Jalali input behavior;
- client encoding of large integer amounts;
- maximum file/page dimensions for interactive preview;
- whether user-selectable Admin density is enabled.

The UI may not invent irreversible answers to these decisions.

---

# 28. Coding Agent Rules

A coding agent implementing this specification must:

1. Use the v1.1 authority set, not historical v1.0 files.
2. Preserve two independent frontend applications.
3. Implement semantic tokens rather than scattered hard-coded styling.
4. Keep gold as a restrained accent.
5. Avoid generic financial CRUD screens.
6. Use exact API status enums.
7. Never create a generic status PATCH UI.
8. Never use JavaScript floating-point for canonical money.
9. Preserve original entered value and unit.
10. Never infer IRR/Toman from amount magnitude.
11. Show request revisions explicitly.
12. Do not implement request-level manager approval.
13. Show manager approval against exact batch version and hash.
14. Block stale approval pages.
15. Keep preview and final exports visually and functionally separate.
16. Never equate download with mark-as-sent.
17. Block quarantined exports without “download anyway”.
18. Implement manual rectangular crop in Phase 1A.
19. Keep crop creation separate from evidence, result, and publication commands.
20. Keep candidate acceptance separate from evidence confirmation.
21. Keep evidence confirmation separate from paid/failed confirmation.
22. Keep publication immutable and versioned.
23. Do not expose full mixed bank bundles to traders.
24. Do not expose raw storage paths.
25. Do not store sensitive files or responses in service-worker or persistent browser cache.
26. Do not queue financial commands offline.
27. Reuse the same idempotency key for timeout recovery of one logical command.
28. Do not auto-retry a mutating command with a new key.
29. Implement `412` and `428` UI explicitly.
30. Do not perform optimistic “approved”, “paid”, “sent”, “published”, or “dispatched” state changes.
31. Respect server permissions and ownership on every screen.
32. Do not give technical admin implicit financial interfaces.
33. Provide accessible labels, focus, keyboard operation, and non-color status cues.
34. Provide numeric alternatives to drag-only crop interactions.
35. Keep telemetry free from financial and personal data.
36. Add loading, empty, error, stale, and background-processing states.
37. Add automated tests for critical component contracts.
38. Add RTL visual-regression coverage for key screens.
39. Document any conflict and stop when a material ADR is unresolved.
40. Report limitations honestly; do not claim production readiness without evidence.

---

# 29. Final UI Principle

Every operational screen must answer:

```text
What requires my action now?
What exact financial amount is involved?
Which immutable version or snapshot am I viewing?
Who owns the next action?
What evidence supports the action?
What can I safely do next?
What happens if the data changed?
Will this action be auditable later?
```

The interface is successful when it converts a sensitive manual process into a clear, structured, private, versioned, and auditable operational workflow without depending on AI or imitating the weaknesses of messaging and spreadsheets.
