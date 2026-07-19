# Gold Trade Settlement Platform

## UI/UX Specification

**Document ID:** `07_UI_UX_Specification`  
**Version:** `1.1`  
**Status:** Revised authoritative UI/UX baseline  
**Language:** English  
**Primary audience:** Product owner, UI/UX designer, frontend engineer, backend engineer, QA engineer, security engineer, technical lead, and coding agents  
**Applies to:** Phase 1A unless a section explicitly identifies a later phase

**Related authoritative documents:**

- `00_Master_Implementation_Blueprint.md`
- `01_Product_Requirements_PRD.md`
- `02_Domain_Model_and_Business_Rules.md`
- `03_System_Architecture.md`
- `04_Database_Schema.md`
- `05_API_Specification.md`
- `06_Workflows_and_State_Machines.md`

**Document authority:**

- This document defines the product-level UI/UX contract.
- Backend state, permissions, calculations, and transition guards remain authoritative.
- Documents `21_UI_Design_System_and_Screen_Specification.md` and `22_UX_User_Journeys_and_Interaction_Guide.md` must be revised later to conform to this version where they conflict.
- Existing manual tools, messaging screenshots, spreadsheets, and paper forms are discovery evidence, not interface templates.

---

# 1. Purpose

This document defines how the Gold Trade Settlement Platform must present and operate its two user-facing applications:

1. **Trader PWA** — a Persian-first, mobile-first application for gold traders and gold shops.
2. **Admin Web App** — a Persian-first, desktop-first responsive application for accountants, managers, dispatch users, authorized business administrators, technical administrators, and read-only users.

The design must support a standardized, controlled, and auditable gold-trade settlement process. It must improve the current manual workflow rather than reproducing messaging applications, spreadsheet layouts, or paper documents.

The primary UX goals are:

- reduce financial input and confirmation errors;
- make the next required action obvious;
- allow high-volume accountant work without unnecessary clicks;
- give managers a precise and trustworthy approval snapshot;
- make trader workflows simple on mobile;
- preserve user context across long operational tasks;
- expose corrections and history without confusing current truth;
- support manual operation without AI, OCR, bank APIs, or automatic matching;
- include a minimal internal manual crop workflow in Phase 1A;
- protect unrelated people’s banking information from trader-facing outputs.

---

# 2. Product Experience Direction

## 2.1 Visual personality

The product must feel:

- premium;
- restrained;
- trustworthy;
- precise;
- modern;
- suitable for high-value financial operations;
- recognizably connected to the gold trade without appearing decorative or ceremonial.

The intended visual direction is **luxury minimalism combined with professional financial-technology UI**.

The interface must not imitate:

- a messaging application;
- an old accounting desktop application;
- a consumer shopping app;
- a cryptocurrency trading terminal;
- a black-and-gold casino aesthetic;
- a decorative jewellery catalogue.

## 2.2 Use of gold styling

Gold is an accent, not the primary surface color.

Recommended behavior:

- use muted gold or warm metallic accents for brand emphasis, selected navigation, key dividers, or premium highlights;
- use neutral, high-contrast surfaces for financial data;
- reserve semantic colors for states such as success, warning, failure, and information;
- do not render every button, badge, border, or table header in gold;
- do not use metallic gradients behind dense operational content;
- do not reduce text contrast for visual elegance.

Exact brand colors, logo, font licensing, and marketing artwork remain separate brand decisions. Frontend implementation must use semantic design tokens rather than hard-coded brand values throughout components.

## 2.3 Surface and density strategy

### Trader PWA

- calm and spacious;
- card-oriented;
- one primary task per screen;
- strong hierarchy;
- large touch targets;
- low cognitive load;
- no dense financial tables in core mobile flows.

### Admin Web App

- controlled information density;
- compact but readable tables;
- persistent filters where useful;
- split views for document review;
- keyboard-friendly navigation;
- clear selection state;
- prominent totals and warnings;
- no decorative whitespace that forces excessive scrolling.

## 2.4 Show current truth, not historical noise

Operational pages must distinguish:

- current authoritative status;
- historical statuses;
- superseded data;
- current publication;
- previous publications;
- current evidence;
- replaced evidence;
- candidate matches;
- confirmed links.

History must remain accessible, but it must not visually compete with the current operational truth.

---

# 3. Core UX Principles

## 3.1 Preserve business intent, redesign execution

The UI must preserve required business controls, including accountant review, manager batch approval, bank-file handling, payment-result confirmation, and auditability.

It may redesign:

- forms;
- page structure;
- work queues;
- batch construction;
- bank document review;
- evidence handling;
- correction flows;
- result publication;
- reporting and search.

A step must not be retained merely because it existed in the manual process.

## 3.2 Manual-first, assistance-ready

Every Phase 1A workflow must remain usable when these capabilities are unavailable:

- OCR;
- AI extraction;
- automatic segmentation;
- automatic matching;
- external beneficiary verification;
- bank APIs;
- SMS.

Optional assistance must be visually separated from authoritative actions.

Use labels such as:

- `Suggested match`;
- `Extracted value — not confirmed`;
- `Needs accountant confirmation`;
- `Low confidence`;
- `Continue manually`.

Never use labels such as:

- `AI approved`;
- `Guaranteed match`;
- `Automatically paid`;
- `Verified by AI` when no human confirmation exists.

## 3.3 Queue-first internal operation

The primary internal experience is not a collection of generic entity tables. It is a set of role-specific work queues.

Each queue must answer:

1. What needs attention?
2. Why does it need attention?
3. How old is it?
4. What is the financial significance?
5. Who owns the task?
6. What is the next valid action?

## 3.4 Strong confirmation proportional to risk

All outgoing payment batches contain high-value financial operations. Manager approval is therefore required for every Phase 1A outgoing batch version.

Strong confirmation must be used for:

- approving or rejecting an exact batch version;
- generating a final bank export;
- marking an exact export as sent;
- confirming a payment attempt as paid or failed;
- replacing primary evidence;
- correcting a published result;
- publishing a result to a trader;
- dispatching gold;
- changing active bank rules;
- activating retention changes.

Confirmation strength must depend on consequences, not on the visual size of the button.

## 3.5 No hidden financial state changes

The UI must use explicit action commands. Generic forms must not expose editable status fields.

Examples of explicit actions:

```text
Submit request
Start accountant review
Request trader correction
Mark eligible for batching
Finalize batch version
Approve exact batch version
Generate final bank export
Mark exact export as sent
Confirm attempt paid
Confirm attempt failed
Replace evidence
Publish result
Register gold dispatch
```

## 3.6 Backend-authoritative allowed actions

Detail endpoints return `allowed_actions`. The frontend uses these to guide the UI, but it must not assume they are authorization proof.

After every sensitive command, the UI must reload or reconcile with the authoritative backend response.

## 3.7 Prevent accidental repetition

For sensitive create or action requests:

- generate and retain an idempotency key for the user action;
- disable the initiating control while the first request is pending;
- do not create a second command on repeated taps;
- when the network response is uncertain, retry with the same key;
- show a resolvable state rather than encouraging the user to submit again blindly.

---

# 4. Application and Device Strategy

## 4.1 Trader PWA

Primary devices:

- Android phones;
- iPhones;
- occasional tablet or desktop browser.

Core requirements:

- mobile-first layout;
- installable PWA where supported;
- camera and gallery upload;
- stable operation on average mobile connections;
- responsive forms with sticky primary actions where useful;
- draft preservation;
- no core horizontal scrolling;
- bottom navigation with at most five primary destinations;
- simplified trader-facing statuses;
- result sharing through the device share sheet when supported.

## 4.2 Admin Web App

Primary devices:

- Windows desktops and laptops;
- wide office monitors;
- manager tablets as a secondary case.

Core requirements:

- desktop-first responsive layout;
- collapsible sidebar;
- workspace width suitable for tables and document previews;
- full keyboard traversal;
- sticky page actions for long screens;
- persistent table filters within a user session;
- safe opening of details in a new tab;
- split-view document processing;
- role-specific dashboards;
- responsive fallback for tablets without reducing security controls.

## 4.3 Independent applications

The Trader PWA and Admin Web App are separate frontend applications.

They may share:

- design tokens;
- typed API client;
- localization foundation;
- money and date utilities;
- status metadata;
- file-upload primitives;
- validation helpers;
- accessibility primitives.

They must not share:

- routes that expose another audience’s application;
- admin navigation in the trader build;
- secrets;
- internal notes or internal response DTOs;
- frontend-only assumptions that replace backend authorization.

---

# 5. Persian, RTL, Numeric, and Date Requirements

## 5.1 Language

Production UI is Persian-first.

All user-visible strings must be externalized through localization resources. Business rules must not depend on translated labels.

English may be used in development environments, but Persian copy is part of Phase 1A acceptance.

## 5.2 RTL and mixed-direction content

Page direction is RTL for Persian interfaces.

The following must use controlled LTR presentation:

- IBAN;
- phone number;
- tracking number;
- account number;
- public reference code;
- UUID shown in technical support contexts;
- hash fragments;
- filename extensions;
- machine error reference.

Requirements:

- use Unicode isolation or explicit direction wrappers to prevent reordered mixed text;
- make IBAN copyable as a continuous normalized value;
- do not place Persian punctuation inside LTR identifiers;
- align numeric table columns consistently;
- test Persian and Latin numerals in paste operations.

## 5.3 Numeral policy

The UI may display Persian digits in ordinary text according to the approved product copy policy. However:

- copied IBANs, phone numbers, references, and tracking numbers must use canonical ASCII digits;
- server requests use canonical numeric values;
- amount parsing must accept Persian and Latin digits;
- copy actions must not include thousands separators unless the user requests formatted copy.

## 5.4 Date and time

- display business dates in Jalali/Shamsi format;
- retain exact time for approvals, submissions, confirmations, and audit events;
- show timezone context on sensitive timestamps where ambiguity is possible;
- show raw bank date separately when it differs from the normalized date;
- never replace an unavailable date with the current date;
- label inferred or manually entered dates clearly.

Example:

```text
تاریخ ثبت: ۱۴۰۵/۰۴/۲۷، ساعت ۱۴:۳۵
تاریخ درج‌شده در سند بانک: ۱۴۰۵/۰۴/۲۶
```

---

# 6. Money Input and Display Standard

## 6.1 Canonical and entered values

The backend canonical value is integer IRR.

The UI must preserve and communicate:

- entered value;
- entered unit;
- canonical IRR value;
- Toman equivalent.

No unit may be inferred from number size.

## 6.2 Trader money input

The trader-facing amount component must provide an explicit unit selector:

```text
تومان | ریال
```

Recommended default for trader workflows: `Toman`, subject to final product configuration.

When the user types:

```text
3,440,000,000 Toman
```

show immediately:

```text
معادل ریالی: 34,400,000,000 IRR
```

Before submission, the review block must show:

- entered amount and unit;
- canonical IRR;
- Toman equivalent;
- amount in words for sensitive submission screens where feasible.

## 6.3 Accountant and bank-file money display

- bank export and reconciliation views treat IRR as authoritative;
- display Toman equivalent as a secondary line or tooltip;
- table sorting and filtering use canonical IRR;
- never abbreviate the only visible amount as `3.4B` in an approval or confirmation context;
- compact abbreviations may appear in dashboards only when the exact value is available on focus or click.

## 6.4 Manager approval money display

The approval header must show:

- exact total IRR;
- exact Toman equivalent;
- amount in words where practical;
- row count;
- request count;
- trader count;
- highest individual row;
- warning count.

## 6.5 Money component requirements

The shared component must support values beyond JavaScript safe integer range without precision loss. Amounts must be transported and formatted as integer strings or a safe big-integer representation.

Recommended interface:

```ts
interface MoneyValue {
  amountIrr: string;
  enteredValue?: string;
  enteredUnit?: "IRR" | "TOMAN";
}
```

The component must not use floating-point arithmetic for conversion or totals.

---

# 7. Information Architecture and Navigation

## 7.1 Trader PWA primary navigation

Recommended mobile navigation:

```text
خانه | درخواست‌ها | نتایج | اعلان‌ها | حساب من
```

`درخواست‌ها` contains two clearly separated categories:

- خرید طلا از مرکز;
- درخواست پرداخت به ذی‌نفع.

Primary quick actions may be shown on the dashboard:

- درخواست خرید طلا;
- درخواست پرداخت جدید.

## 7.2 Trader route structure

```text
/login
/pending-approval
/dashboard
/requests
/payment-requests
/payment-requests/new
/payment-requests/:id
/gold-sales
/gold-sales/new
/gold-sales/:id
/results
/results/:publicationId
/notifications
/profile
```

Trader routes must never accept another trader identifier as a means of changing ownership scope.

## 7.3 Admin primary navigation

Recommended sidebar groups:

```text
Overview
  Dashboard
  Work Queues

Outgoing Payments
  Payment Requests
  Payment Batches
  Bank Exports
  Bank Results

Gold Operations
  Gold Sales
  Incoming Payment Verification
  Gold Dispatch

Business Directory
  Traders
  Beneficiaries

Control and Insight
  Reports
  Audit

Administration
  Bank Configuration
  Users and Roles
  System Operations
```

## 7.4 Role-specific navigation

### Accountant

- operational dashboard;
- outgoing request review;
- batch building;
- bank exports;
- bank results and crop workspace;
- payment attempt confirmation;
- incoming payment verification;
- review tasks;
- reports permitted by RBAC.

### Manager

- approval dashboard;
- exact batch-version approval queue;
- exception and correction queue;
- manager reports;
- permitted audit views.

### Dispatch user

- gold dispatch queue;
- dispatch detail;
- delivery issue queue.

### Technical administrator

- service status;
- file-processing failures;
- bank configuration where authorized;
- feature configuration;
- users and roles where authorized.

Technical administrators must not receive default navigation for day-to-day financial confirmation unless their assigned permissions explicitly allow it.

---

# 8. Shared Interaction Components

## 8.1 Page header

Operational page headers should include:

- page title;
- public reference;
- current status;
- important amount if applicable;
- current owner/assignee if applicable;
- last updated time;
- primary allowed action;
- secondary action menu.

## 8.2 Status presentation

Do not rely on color alone.

Each status indicator must include:

- Persian text label;
- semantic icon or shape where useful;
- color token;
- optional explanation;
- timestamp for major transitions.

Trader labels may be simpler than backend statuses. Admin details must show the exact backend status and the user-friendly label.

## 8.3 Record version and stale-data indicator

Mutable internal pages must retain the latest ETag/record version.

When the server returns a version conflict:

- do not overwrite the page silently;
- show that another user changed the record;
- preserve the user’s unsaved note where possible;
- offer `Reload latest data`;
- show a concise comparison when feasible;
- require the user to review before resubmitting.

## 8.4 Public references

Business users see public references rather than UUIDs.

Examples:

```text
PR-14050427-000123
PB-14050427-000018
PBV-000018-03
EXP-14050427-000041
BRB-14050427-000009
```

Technical IDs may appear in a support drawer accessible to authorized users.

## 8.5 Copy actions

Provide explicit copy actions for:

- IBAN;
- tracking number;
- payment request reference;
- batch reference;
- exact amount;
- generated trader-visible result summary.

After copying, show a brief confirmation without obscuring data.

## 8.6 Structured notes

The platform does not include internal chat in Phase 1A.

Use purpose-specific fields:

- internal accountant note;
- manager decision note;
- correction reason;
- trader-visible correction message;
- failure reason;
- dispute message;
- closure reason.

Every note input must indicate whether it is:

```text
Internal only
Visible to trader
Included in publication
```

## 8.7 Timeline and audit

### Trader timeline

Show only trader-safe business events.

### Admin operational timeline

Show major domain events and current truth.

### Full audit panel

Available only to authorized roles and collapsed by default. It must identify superseded records and exact versions.

## 8.8 Warning system

Warnings require:

- severity;
- concise title;
- explanation;
- affected field or row;
- blocking/non-blocking classification;
- resolution action where applicable.

Examples:

- duplicate IBAN/request possibility;
- current beneficiary is blocked;
- request revision changed after batch preparation;
- batch approval invalidated;
- export integrity mismatch;
- same amount appears in several attempts;
- evidence includes a mixed document;
- publication will supersede a previous result.

---

# 9. Form Standards

## 9.1 Draft preservation

Trader forms must preserve draft data:

- when navigating temporarily away;
- after recoverable validation errors;
- after session renewal where safe;
- after upload retry;
- when the browser is backgrounded.

Do not retain sensitive form data indefinitely on a shared device. Local draft behavior must be documented and clearable.

## 9.2 Review before submission

Financial submissions require a final review surface rather than immediate submission from the last input field.

The review must emphasize:

- beneficiary;
- IBAN;
- exact amount and unit;
- canonical IRR;
- attachments;
- consequences;
- current request revision.

## 9.3 Amount input

- accept Persian and Latin digits;
- ignore ordinary separator characters;
- reject decimal money values;
- display formatted value while retaining precise canonical value;
- show unit selector continuously;
- show both IRR and Toman before submit;
- highlight a unit change because it materially changes the amount.

## 9.4 IBAN input

- show in LTR;
- accept paste with spaces or hyphens;
- normalize to uppercase continuous form;
- validate Iranian IBAN structure and checksum where implemented;
- display grouped chunks for reading while copy returns canonical form;
- provide a second visual confirmation on high-value requests;
- do not claim ownership verification without a real provider response.

## 9.5 File input

On mobile:

- camera;
- photo library;
- file browser.

Before upload:

- show thumbnail or file identity;
- allow removal/replacement;
- allow image rotation where feasible;
- warn when an image is unusually low resolution;
- do not claim image quality guarantees.

## 9.6 Unsaved-change guard

When a user leaves a materially changed form:

- warn before discarding;
- allow save as draft where supported;
- do not show the warning when no material change exists.

---

# 10. Trader PWA Screens

## 10.1 Login and account-state screens

Support the authentication method selected by ADR-001 without coupling screens to token implementation.

States:

- normal login;
- invalid credentials;
- rate limited;
- password recovery/help;
- pending approval;
- suspended;
- inactive;
- session expired.

Pending and suspended pages must explain available actions without exposing security-sensitive account details.

## 10.2 Trader dashboard

Required content:

- items needing trader action;
- submitted payment requests;
- results recently published;
- active gold-sale orders;
- unread notifications;
- recent activity.

Primary actions:

- create payment request;
- create gold-sale request;
- open latest result.

Do not turn the dashboard into an analytics page. The priority is action and status.

## 10.3 Beneficiary selection and management

The request form may:

- select a saved beneficiary;
- create a new beneficiary inline;
- show recently used beneficiaries;
- warn about possible duplicates;
- clearly show blocked/inactive records;
- require explicit confirmation before using a beneficiary whose IBAN changed.

Editing a beneficiary master record must not suggest that previous financial records will change.

## 10.4 Create outgoing payment request

Recommended sections:

1. Beneficiary.
2. Amount.
3. Purpose and optional business metadata.
4. Attachments.
5. Review and submit.

Required fields in Phase 1A:

- beneficiary/account-owner name;
- Iranian destination IBAN;
- amount value;
- explicit unit;
- canonical IRR confirmation.

Optional fields:

- national ID;
- phone;
- description;
- gold weight/purity where business-relevant;
- supporting attachment.

Actions:

- save draft;
- review submission;
- submit;
- save and create another.

`Save and create another` must not carry over beneficiary, IBAN, or amount by default. The user may explicitly choose to reuse a beneficiary.

## 10.5 Request detail and revision UX

Show:

- current request status;
- current revision data;
- submitted date;
- amount;
- beneficiary;
- safe timeline;
- correction message when applicable;
- payment attempts once created;
- current published result when available.

When a correction is requested:

- highlight only fields requiring attention;
- show the accountant’s trader-visible message;
- create a new revision on save;
- show a review of changes before resubmission;
- do not expose internal notes or previous internal decisions.

## 10.6 Request list

Mobile cards show:

- beneficiary;
- exact amount with selected primary unit;
- concise status;
- last meaningful update;
- action-needed indicator;
- result availability.

Filters:

- action required;
- status group;
- beneficiary;
- date;
- amount range;
- result available.

## 10.7 Split attempts on trader view

The trader should understand one original request without needing to understand bank batching internals.

Recommended display:

```text
Total requested: 450,000,000 Toman
Paid: 400,000,000 Toman
Remaining: 50,000,000 Toman

Transfer parts
1. Paid — 200,000,000 Toman
2. Paid — 200,000,000 Toman
3. Waiting for bank result — 50,000,000 Toman
```

Do not show internal batch hash, source account, or manager notes.

## 10.8 Payment result publication screen

The trader views an immutable publication, not a live assembly of unrelated current tables.

Show:

- publication version/current indicator;
- request reference;
- beneficiary;
- masked or policy-approved IBAN display;
- exact amount;
- payment date;
- bank;
- tracking number;
- selected safe evidence;
- published time;
- correction notice if this publication supersedes an earlier result;
- acknowledge result;
- report issue;
- download/share.

The UI must clearly label a superseded publication when opened through history or an old link.

## 10.9 Share behavior

Preferred share order:

1. structured generated result card;
2. structured text summary;
3. safe evidence file only when explicitly approved for sharing.

The generated card must exclude:

- internal notes;
- full mixed bank documents;
- unrelated transactions;
- other traders’ data;
- internal actor identities;
- technical IDs.

## 10.10 Trader dispute

Issue types:

- beneficiary reports non-receipt;
- amount appears incorrect;
- beneficiary/IBAN appears incorrect;
- tracking information is unclear;
- evidence appears unrelated;
- other.

The dispute screen must:

- reference the exact publication version;
- accept a description;
- accept an optional attachment;
- explain that submitting a dispute does not automatically reverse a bank payment;
- show subsequent resolution status.

## 10.11 Gold-sale request and incoming payment evidence

The trader flow must support:

- creating a gold-sale request;
- viewing price/expected amount once set;
- submitting one or more payment evidences;
- showing total submitted/verified/remaining amounts;
- receiving correction requests;
- viewing dispatch or settlement status;
- acknowledging receipt where applicable.

Amount mismatch must be shown as a warning, not silently corrected.

---

# 11. Admin Dashboard and Work Queues

## 11.1 Accountant dashboard

Prioritize:

- new requests awaiting review;
- requests returned and resubmitted;
- eligible requests waiting for batch preparation;
- batches requiring accountant correction;
- final exports ready to download/send;
- batches waiting for bank results;
- bank bundles requiring review;
- unmatched segments;
- failed and partial attempts;
- incoming payment verification;
- trader disputes;
- processing failures affecting work.

Show count and financial total where meaningful.

## 11.2 Manager dashboard

Prioritize:

- exact batch versions awaiting approval;
- total amount awaiting approval;
- oldest waiting approval;
- highest-value batch;
- warnings and overrides;
- sensitive published-result correction requests;
- gold/incoming-payment exceptions requiring manager decision;
- rejected versions awaiting replacement.

The manager dashboard must not be dominated by accountant operational detail.

## 11.3 Queue behavior

Queue rows/cards must include:

- public reference;
- entity type;
- trader;
- amount;
- current state;
- reason for queue entry;
- warning count;
- age;
- priority;
- assignment;
- next action.

Safe bulk actions:

- select eligible requests for a batch preview;
- assign review tasks;
- export non-sensitive reports;
- mark notifications read.

Unsafe bulk actions in Phase 1A:

- confirm multiple payments paid;
- approve multiple batches without opening exact versions;
- publish multiple results without individual validation;
- replace evidence in bulk;
- cancel executed financial records.

---

# 12. Accountant Payment Request Review

## 12.1 Workspace layout

Recommended desktop layout:

```text
Header: reference, trader, amount, status, next action
Main left: current revision and attachments
Main right: validation, warnings, trader history summary
Bottom: timeline, internal notes, revision history
```

## 12.2 Required data

- current request revision;
- beneficiary snapshot;
- normalized IBAN;
- amount in IRR and Toman;
- entered unit/value;
- trader;
- attachments;
- duplicate warnings;
- blocked-beneficiary warning;
- revision history;
- open tasks;
- allowed actions.

## 12.3 Actions

- start review;
- request correction;
- mark eligible for batching;
- cancel where allowed;
- create internal correction revision with permission and reason;
- add internal note.

Do not use `Approve by manager` or `Ready for manager approval` on a Payment Request. Manager approval applies only to an exact Batch Version.

## 12.4 Sensitive internal revision

When an authorized internal user changes amount, IBAN, or beneficiary:

- open an explicit correction flow;
- require reason;
- show before/after comparison;
- create a new immutable request revision;
- show downstream impact;
- invalidate or replace unsent batch allocations as required;
- never imply historical attempts or exports changed.

---

# 13. Batch Builder and Version Workflow

## 13.1 Batch selection preview

The accountant selects eligible request revisions and chooses:

- bank profile version;
- bank mapping/template version;
- source account;
- effective processing time/context;
- applicable split rules.

The preview shows:

- selected request count;
- generated attempt count;
- exact total;
- per-request split result;
- validation errors;
- blocking warnings;
- duplicate allocation warnings;
- bank rule applied to each split.

Preview does not create manager approval authority.

## 13.2 Draft Batch Version editor

Show the exact ordered rows of the current draft version.

Columns:

- order;
- attempt reference;
- request reference;
- trader;
- beneficiary;
- destination IBAN;
- amount IRR;
- Toman equivalent;
- optional deposit identifier;
- bank description/reference;
- warning state;
- source request revision.

Actions:

- remove row through controlled replacement behavior;
- regenerate split preview where allowed;
- reorder only if bank rules permit;
- create replacement version;
- validate;
- finalize for approval.

## 13.3 Finalization UX

Before finalizing:

- show row count and total;
- show all blocking validation errors;
- show unresolved warnings separately;
- identify exact bank profile/mapping/source account;
- explain that the version becomes immutable;
- require confirmation.

After finalization:

- lock row editing;
- show version number and content-hash fingerprint;
- create manager task;
- expose `Create replacement version` rather than `Edit`.

## 13.4 Rejected or invalidated version

A rejected/invalidated version remains viewable.

Show:

- decision reason;
- manager;
- decision time;
- approved/rejected hash;
- replacement version link if created;
- exact differences between versions where practical.

---

# 14. Manager Exact Batch-Version Approval

## 14.1 Approval page hierarchy

Top summary must show:

- `Batch PB-... / Version N`;
- exact total IRR;
- exact Toman equivalent;
- amount in words where feasible;
- bank;
- source account;
- row count;
- request count;
- trader count;
- beneficiary count;
- highest row amount;
- warnings;
- preparer;
- finalized time;
- content-hash fingerprint.

## 14.2 Row review

The manager can:

- search rows;
- filter warnings;
- sort by amount/trader/beneficiary;
- inspect a request and its revision in a side drawer;
- inspect validation summary;
- view a clearly marked preview export;
- compare with a prior rejected version.

The manager is not required to click approval for every ordinary row.

## 14.3 Approval action

The approval confirmation must repeat:

- exact version;
- total;
- row count;
- bank;
- source account;
- content fingerprint;
- consequence that a final sendable export may be generated.

Recent authentication is required according to security policy. If the recent-auth window has expired, request re-authentication without losing page context.

## 14.4 Rejection

Rejection requires a reason and optional row references.

The page must explain:

- the finalized version will remain immutable;
- the accountant must create a replacement version;
- the rejected version remains in history.

## 14.5 Stale approval page

If a version is no longer current or its approval state changed in another session:

- block decision submission;
- show `This approval view is no longer current`;
- offer navigation to the current version;
- do not silently transfer the user’s approval to another version.

---

# 15. Bank Export UX

## 15.1 Preview export

Preview exports must have a persistent visual and technical marker:

```text
PREVIEW — NOT APPROVED FOR BANK SUBMISSION
```

They must not present a `Mark sent` action.

## 15.2 Final export

The final-export screen shows:

- exact approved batch version;
- approval reference;
- bank profile/mapping version;
- source account;
- row count;
- total;
- validation result;
- file checksum fragment;
- generated time;
- generated by/system job;
- current file status.

## 15.3 Download

Before download, the user sees an integrity check status.

States:

- validating;
- available;
- integrity mismatch — blocked;
- generation failed;
- quarantined;
- voided.

## 15.4 Mark exact export as sent

This action belongs to a specific export, not merely to the batch.

Confirmation requires:

- exact export reference;
- exact batch/version;
- file name;
- total;
- row count;
- sent time;
- submission channel;
- optional note.

The UI must state:

```text
Downloading the file does not mean it was sent to the bank.
```

---

# 16. Bank Result Bundle Upload and Review

## 16.1 Upload

Support:

- one or more images;
- PDF;
- scanned PDF;
- supported spreadsheets;
- mixed file bundles.

Do not force one related Batch.

Show:

- bank profile when known;
- received date;
- file list;
- page count where available;
- upload progress;
- validation status;
- duplicate-file warning;
- original-file preservation message;
- internal note.

## 16.2 Review workspace

The required desktop layout is a split workspace:

```text
Top: bundle summary, progress, search, next/previous unresolved
Left: source document viewer
Right: selected segment/result form and payment-attempt search
Bottom/right drawer: candidates, confirmed link, history, open tasks
```

A tab-only fallback may be used on smaller screens, but desktop implementation should preserve simultaneous document and payment context.

## 16.3 Document viewer

Required Phase 1A controls:

- page thumbnails;
- current page indicator;
- zoom in/out;
- fit width/page;
- pan;
- rotate view;
- full-screen mode;
- manual rectangular crop;
- file switcher;
- download original for authorized internal users;
- display processing errors without blocking manual review.

## 16.4 Search for payment attempts

Search by:

- attempt reference;
- request reference;
- trader;
- beneficiary;
- normalized IBAN;
- exact amount;
- amount range;
- tracking number;
- batch/export;
- sent date;
- bank.

Results must show enough context to distinguish repeated amounts and names.

## 16.5 Review progress

Show:

- files/pages reviewed;
- segment count;
- confirmed links;
- failed results;
- unresolved segments;
- irrelevant/unknown dispositions;
- open tasks;
- bundle closure readiness.

Closing a bundle with unresolved content requires explicit disposition and reason.

---

# 17. Phase 1A Manual Crop Workspace

## 17.1 Crop behavior

The accountant selects a rectangle over a rendered page/image.

Coordinates sent to the API must be normalized between `0` and `1` and include:

- source file;
- page;
- rotation;
- client source dimensions;
- normalized x/y/width/height.

## 17.2 Crop preview

Before save:

- show selected crop;
- allow adjustment;
- show page and file source;
- warn when the crop may contain unrelated transaction data;
- allow cancellation without creating a Segment.

## 17.3 Saving

Saving creates a Receipt Segment and may queue deterministic rendering.

UI states:

- creating segment;
- rendering crop;
- crop ready;
- rendering failed — retry or use structured/manual evidence;
- segment superseded;
- segment voided.

## 17.4 Rotation

Viewer rotation must not corrupt crop coordinates. The UI must send the rotation/provenance required by the API contract.

## 17.5 Privacy review

Before including a crop in a trader publication, the accountant must see a privacy confirmation:

- only the relevant transaction is visible;
- unrelated names, IBANs, amounts, or tracking numbers are excluded;
- the crop matches the selected payment attempt.

---

# 18. Payment Attempt Result Confirmation

## 18.1 Confirmation workspace

Display side by side:

- selected payment attempt snapshot;
- selected evidence/segment;
- structured bank-result fields;
- request aggregate progress;
- warning/candidate context.

## 18.2 Confirm paid

Required or policy-dependent fields:

- attempt;
- exact attempt amount;
- result date when available;
- tracking number when available;
- primary evidence or governed text-only reason;
- accountant note for exceptions.

Before confirm, show:

- trader;
- beneficiary;
- IBAN;
- attempt amount;
- request total;
- paid sum after confirmation;
- remaining amount after confirmation;
- evidence preview;
- effect on request status.

## 18.3 Confirm failed

Require:

- failure reason code;
- optional bank note;
- whether retry review is required;
- evidence when available.

Do not automatically create a materially changed retry from this dialog.

## 18.4 Text-only confirmation

If permitted by the final security/business policy:

- present it as an exception;
- require elevated permission;
- require a detailed reason;
- show a strong warning;
- create a review/audit marker;
- do not make text-only evidence visually indistinguishable from bank evidence.

## 18.5 Overpayment guard

If confirmation would cause authoritative paid sum to exceed the request amount:

- block ordinary confirmation;
- show the computed overpayment;
- create or direct to a reconciliation flow;
- do not offer a simple `Confirm anyway` button.

---

# 19. Retry and Correction UX

## 19.1 Retry

The retry flow must show:

- original attempt;
- failure reason;
- remaining request amount;
- current request revision;
- material differences from the attempt snapshot;
- intended retry amount;
- requirement for later batch inclusion and approval.

Changing beneficiary or IBAN requires a Request Revision before creating the retry.

## 19.2 Evidence replacement

The replacement flow must show:

- current primary evidence;
- new evidence;
- before/after preview;
- reason;
- whether the old evidence was published;
- whether trader notification will be generated;
- whether a sensitive correction review is required.

The action is `Replace evidence`, not `Delete evidence`.

## 19.3 Published result correction

The UI must never rewrite an active Publication in place.

Correction flow:

1. inspect current publication;
2. identify incorrect fields/evidence;
3. enter reason;
4. complete required manager/dual-control review according to policy;
5. preview new publication version;
6. publish replacement;
7. show old publication as superseded;
8. notify trader.

## 19.4 Closed request correction

Do not expose a casual `Reopen` toggle.

Use a governed correction request that shows:

- closure history;
- reason;
- affected publication/attempt/evidence;
- required approval;
- resulting current state.

---

# 20. Gold Sale and Incoming Payment UX

## 20.1 Gold-sale detail

Show separate sections for:

- requested gold details;
- pricing snapshot/version;
- expected payment;
- submitted incoming payments;
- verified amount;
- under/overpayment;
- bank-statement matches;
- dispatch guard;
- physical dispatch or non-physical settlement;
- timeline and disputes.

## 20.2 Bank statement import

The import flow must include:

- bank profile/mapping version;
- source account;
- date range;
- file upload;
- parse run status;
- row count;
- invalid row count;
- duplicate warning count;
- preview;
- import-run history.

A reparse creates a new run and must not appear as though previous rows were edited.

## 20.3 Incoming payment matching

Display:

- receipt/evidence;
- expected order amount;
- already verified amount;
- candidate statement rows;
- exact amount/date/tracking comparison;
- duplicate-use warning;
- selected match;
- resulting verified/remaining amount.

## 20.4 Dispatch guard

Dispatch action must show whether the order is eligible.

When blocked, display the exact reason:

- payment not fully verified;
- unresolved manager exception;
- open dispute;
- missing required dispatch data.

An override, when allowed, requires explicit permission, reason, and strong confirmation.

---

# 21. Tables, Filters, and Productivity

## 21.1 Table requirements

Admin tables support:

- server-side pagination;
- sorting from an allowlist;
- multi-filter controls;
- search;
- column visibility;
- sticky header where useful;
- row selection only when a safe action exists;
- exact amount alignment;
- status and warning indicators;
- saved/persistent views where feasible;
- open detail in new tab.

## 21.2 Density modes

The Admin Web App may provide:

- comfortable;
- compact.

Compact mode must preserve accessibility and touch/click target minimums.

## 21.3 Filter persistence

Returning from a detail page should restore:

- page/cursor;
- filters;
- sorting;
- selected queue tab;
- scroll context where feasible.

## 21.4 No hidden truncation

- IBAN may be visually shortened in a list but full value must be available by permission-controlled reveal/copy;
- amount must not be truncated without exact accessible value;
- long notes may be collapsed with an explicit expansion action;
- status explanations must not be hidden only in hover tooltips.

---

# 22. File Upload, Preview, and Processing UX

## 22.1 File lifecycle presentation

Map backend file states to clear UI states:

```text
Selected
Uploading
Uploaded — validating
Quarantined / unavailable
Available
Processing preview
Preview ready
Processing failed
Archived
Retention pending
Deleted by governed policy
```

Do not label a file `Ready` before backend availability is confirmed.

## 22.2 Failure recovery

- preserve the related form when upload fails;
- retry upload without duplicating the business entity;
- display a request/error reference;
- allow removal of failed temporary uploads;
- distinguish network failure from rejected file type or quarantine.

## 22.3 Preview authorization

Preview and download are separate authorized actions. A thumbnail or cached preview must not bypass ownership checks.

## 22.4 Original and derived files

The UI must identify:

- original upload;
- normalized preview;
- manual crop;
- generated result card;
- replaced/superseded evidence.

A derived crop must link back to its source for authorized internal users.

---

# 23. Confirmation Dialog Standard

## 23.1 Ordinary confirmation

For low-risk actions, use a standard concise dialog.

## 23.2 Financial confirmation

For high-risk actions, use a review dialog or full-screen confirmation surface containing:

- action title;
- exact entity/version;
- exact amount;
- actor role;
- critical fields;
- consequence;
- warnings;
- required note where applicable;
- confirmation control with action-specific wording.

Avoid generic `Yes` buttons.

Examples:

```text
Approve Batch Version 3
Confirm Attempt Paid
Mark Export EXP-... as Sent
Publish Corrected Result Version 2
```

## 23.3 Destructive/corrective confirmation

Do not require users to type generic phrases for every action. Typed confirmation may be reserved for exceptional operations such as activating a lower retention period or revoking a published result without replacement.

---

# 24. Status and Trader-Label Mapping

The frontend must consume canonical backend statuses. The following mapping is the baseline; final Persian copy must be approved before release.

## 24.1 Payment Request

| Backend status | Admin meaning | Trader-facing concept |
|---|---|---|
| `draft` | Editable current draft | Draft |
| `submitted_to_center` | Submitted, not yet actively reviewed | Sent to center |
| `under_accountant_review` | Accountant is reviewing | Under review |
| `needs_trader_correction` | Trader action required | Needs correction |
| `eligible_for_batching` | Valid for internal batch selection | Preparing payment |
| `batched` | Allocated to current batch version | Preparing payment |
| `sent_to_bank` | Exact export marked sent | Sent to bank |
| `partially_paid` | Some authoritative attempts paid | Partially paid |
| `paid` | Exact requested amount covered | Paid — result being prepared |
| `failed` | Terminal failed outcome currently selected | Payment failed |
| `retry_required` | Remaining amount requires another attempt | Follow-up in progress |
| `result_ready_for_trader` | Publication preview validated | Result being prepared |
| `result_published` | Active publication exists | Result available |
| `trader_acknowledged` | Trader acknowledged publication | Confirmed by you |
| `trader_disputed` | Trader dispute open | Issue reported |
| `cancelled` | Cancelled before/under governed conditions | Cancelled |
| `closed` | Operationally closed | Closed |

## 24.2 Payment Attempt

| Backend status | UI label concept |
|---|---|
| `created` | Created |
| `included_in_batch_version` | Included in batch version |
| `sent_to_bank` | Sent to bank |
| `bank_result_pending` | Waiting for bank result |
| `paid` | Paid |
| `failed` | Failed |
| `retry_required` | Retry required |
| `superseded` | Replaced by newer attempt |
| `cancelled` | Cancelled before sending |

## 24.3 Payment Batch

| Backend status | UI label concept |
|---|---|
| `draft` | Draft batch |
| `ready_for_approval` | Awaiting manager approval |
| `approved` | Exact version approved |
| `approval_invalidated` | Approval invalidated by replacement/change |
| `exported` | Final export generated |
| `sent_to_bank` | Exact export marked sent |
| `result_received` | Bank result received |
| `partially_resolved` | Partially resolved |
| `resolved` | Resolved |
| `rejected` | Version rejected |
| `cancelled` | Cancelled before sending |

## 24.4 Batch Version

| Backend status | UI label concept |
|---|---|
| `draft` | Editable draft version |
| `ready_for_approval` | Immutable and awaiting decision |
| `approved` | Approved version |
| `rejected` | Rejected version |
| `superseded` | Replaced by another version |

## 24.5 Publication

| Backend status | UI label concept |
|---|---|
| `active` | Current result |
| `superseded` | Replaced result |
| `revoked` | No longer valid |

---

# 25. Authentication and Session UX

## 25.1 Transport independence

The UI specification does not assume whether the final implementation uses server sessions or a secure refresh-token design. The frontend must not store long-lived secrets in insecure browser storage.

## 25.2 Session expiration

When a session expires:

- stop rendering protected content;
- preserve unsent non-sensitive draft data where safe;
- show a clear re-authentication path;
- return the user to the previous context after successful login when authorized;
- never expose cached internal data after logout.

## 25.3 Recent authentication

For manager approval and other selected high-risk actions:

- re-authenticate in a modal or dedicated route;
- preserve approval context;
- show expiry of the recent-auth window only when useful;
- never treat opening the approval page as recent authentication.

## 25.4 Authorization changes

If a role or permission is removed during a session:

- hide/disable affected actions on refresh;
- handle a backend `403` without exposing data;
- do not keep sensitive data cached indefinitely.

---

# 26. Security and Privacy UX

## 26.1 Trader isolation

Trader-facing pages must never expose:

- another trader’s request;
- full mixed bank bundles;
- unrelated receipt segments;
- internal notes;
- manager comments;
- internal audit events;
- source center account details unless explicitly part of the safe publication policy;
- private bank mapping or rules.

## 26.2 Sensitive values

Internal users may need complete IBANs. Trader-facing result views may mask them according to policy while preserving enough digits for confirmation.

Copying a masked value must not unexpectedly copy the full value unless the user is authorized and the action says so.

## 26.3 Screen privacy

For high-sensitivity internal views:

- avoid displaying full banking data in global navigation or toast messages;
- do not include sensitive values in browser page titles;
- mask data in inactivity/lock overlays;
- use no sensitive information in analytics event names or URLs.

## 26.4 Download and sharing

- every download is authorized at request time;
- signed links are short-lived;
- share files contain only publication-approved information;
- old/superseded share files must be governed by publication policy;
- the UI must warn before downloading a full internal mixed bundle.

---

# 27. Error, Loading, Empty, and Recovery States

## 27.1 Loading

Use skeletons for ordinary reads and explicit progress for commands.

Do not show a completed state before backend confirmation.

## 27.2 Empty state

Every queue/list empty state should explain:

- what the list represents;
- whether the user needs to act;
- where future items will come from.

## 27.3 Error references

Show:

- user-friendly message;
- field errors where applicable;
- retry action where safe;
- support/error reference;
- no stack trace or internal path.

## 27.4 Dependency degradation

Examples:

### Redis/worker unavailable

```text
Background file processing is temporarily unavailable. Existing records remain accessible. You may continue with operations that do not require a new preview/export job.
```

### AI unavailable

```text
Automatic assistance is unavailable. Continue with manual review.
```

### Storage unavailable

Block new upload/evidence commands and clearly indicate that existing metadata may still be viewed.

## 27.5 Unknown result after timeout

When a financial command times out:

- do not show `Failed` immediately;
- query by idempotency key/refresh the entity;
- show `Checking whether the action was completed`;
- allow a safe retry using the same idempotency key.

---

# 28. Accessibility and Usability

Minimum target: WCAG 2.1 AA principles for core workflows, subject to formal testing.

Requirements:

- keyboard navigation in Admin Web App;
- visible focus states;
- semantic labels;
- error association with fields;
- screen-reader text for icons;
- no color-only meaning;
- sufficient contrast;
- reduced-motion support;
- touch target sizing appropriate for mobile;
- no drag-only requirement for crop adjustment or row reordering;
- accessible alternative controls for zoom, rotate, and page navigation;
- tables with meaningful headers;
- dialog focus trapping and restoration;
- logical RTL tab order.

---

# 29. Performance UX

## 29.1 Lists

- server-side pagination or cursor pagination;
- debounced search;
- cancel stale requests;
- no loading of all records into the browser;
- virtualized rendering only where needed and accessible.

## 29.2 Files

- progressive previews;
- thumbnails before full-resolution render;
- page-level PDF loading;
- no automatic download of full mixed bundles;
- background crop/export processing.

## 29.3 Perceived performance

- preserve list context;
- show command progress;
- show processing jobs independently from page navigation;
- notify users when long-running export/crop jobs complete;
- do not use fake progress that reaches 100% before backend completion.

---

# 30. Analytics and Telemetry Boundaries

Product analytics, if enabled, must not collect:

- full IBAN;
- account numbers;
- national IDs;
- receipt image contents;
- raw notes;
- beneficiary names;
- exact financial records in third-party analytics.

Allowed events should be generic, for example:

```text
payment_request_form_opened
payment_request_submitted
batch_version_finalized
manager_approval_completed
crop_job_failed
```

Operational audit is separate from product analytics.

---

# 31. Phase 1A UI Scope

## 31.1 Trader PWA required

- authentication and account-state screens;
- dashboard;
- beneficiary selection/creation;
- outgoing payment request draft/review/submit;
- correction and revision resubmission;
- request list/detail;
- attempt progress summary;
- active publication/result view;
- secure download/share;
- acknowledge/dispute;
- gold-sale request;
- incoming payment evidence;
- dispatch/settlement status;
- notifications;
- profile/help.

## 31.2 Admin Web App required

- authentication/session UX;
- role-specific dashboard;
- work queues;
- trader approval/management;
- beneficiary management;
- payment request review and revisions;
- eligible-request selection;
- batch preview and draft version;
- finalize version;
- manager exact-version approval/rejection;
- preview and final bank export;
- mark exact export sent;
- bank result bundle upload;
- split document review workspace;
- image/PDF preview with zoom, rotate, page navigation;
- minimal rectangular internal crop;
- attempt search and result confirmation;
- confirmed evidence link and replacement;
- immutable publication preview/create/correction;
- manual review tasks;
- gold-sale/incoming-payment verification;
- statement import runs;
- dispatch/settlement;
- operational reports;
- audit views;
- bank configuration views;
- system-processing status appropriate to role.

## 31.3 Not required in Phase 1A

- automatic segmentation;
- mandatory OCR;
- AI final decisions;
- bank API integration;
- internal real-time chat;
- native mobile apps;
- seller/beneficiary login;
- multi-company tenant switching;
- subscription/billing UI;
- advanced anomaly dashboards;
- fully customizable workflow designer;
- dark mode.

---

# 32. Future UI Extension Hooks

Future features must attach to existing authoritative workflows rather than replace them.

Possible hooks:

- OCR-extracted fields panel;
- automatic segment proposals;
- matching candidate score/reason panel;
- beneficiary verification result;
- bank API ingestion status;
- anomaly warning panel;
- advanced reporting;
- multi-company navigation in Phase 4;
- configurable notification channels.

AI panels must remain collapsible and clearly advisory.

---

# 33. Frontend API Integration Rules

## 33.1 Typed contracts

Use an OpenAPI-generated or equivalently typed client. Do not manually duplicate financial enums in disconnected files.

## 33.2 ETag and `If-Match`

For mutable records:

- store response ETag;
- send `If-Match` for required updates;
- handle `412 VERSION_CONFLICT`;
- handle `428 PRECONDITION_REQUIRED`;
- never retry a stale update automatically with a new version.

## 33.3 Idempotency

For required commands:

- create a stable key when the user begins the command;
- reuse it after timeout/retry;
- never generate a second key merely because the first response was lost;
- clear it after an authoritative completed response or deliberate abandonment.

## 33.4 Error handling

Map API codes to action-oriented UI messages, including:

- `VERSION_CONFLICT`;
- `PRECONDITION_REQUIRED`;
- `IDEMPOTENCY_KEY_REUSED`;
- `INVALID_STATE_TRANSITION`;
- `BATCH_VERSION_NOT_CURRENT`;
- `APPROVAL_HASH_MISMATCH`;
- `EXPORT_INTEGRITY_MISMATCH`;
- `FILE_NOT_AVAILABLE`;
- `EVIDENCE_LINK_CONFLICT`;
- `AMOUNT_UNIT_MISMATCH`;
- `OVERPAYMENT_RECONCILIATION_REQUIRED`.

## 33.5 Polling/background jobs

- poll with backoff or use later real-time updates;
- allow navigation away;
- show job result in notifications/work queue;
- stop polling terminal jobs;
- do not make worker completion a financial approval.

---

# 34. QA and UX Acceptance Criteria

## 34.1 Trader safety

- Trader sees only owned data.
- Core screens work without horizontal scrolling on supported mobile widths.
- Amount unit is always explicit.
- Submission review shows entered unit and canonical IRR.
- Trader can correct a returned request through a new revision.
- Trader sees only an active safe publication by default.
- Superseded publication is clearly labeled.
- Mixed bank documents are never exposed through trader routes.
- Dispute references the exact publication.

## 34.2 Accountant productivity

- Queues identify next action and financial total.
- Filters persist when returning from detail.
- Request review can mark `eligible_for_batching` without manager approval at request level.
- Batch builder shows exact split rows and validation.
- Document review supports simultaneous source preview and attempt search.
- Manual crop can be completed without an external image editor.
- Attempt confirmation shows aggregate effect.
- Evidence replacement preserves old evidence.
- Network retry does not duplicate commands.

## 34.3 Manager control

- Manager approves an exact immutable Batch Version.
- Approval screen shows total, row count, bank, source account, version, warnings, and fingerprint.
- Recent authentication is enforced without losing context.
- Stale approval pages cannot approve a replacement version.
- Rejection requires a reason.
- Manager does not need to approve each ordinary request individually.

## 34.4 Export integrity

- Preview export cannot be marked sent.
- Final export is tied to an approved version.
- Integrity mismatch blocks download.
- Mark sent references an exact export.
- Download does not automatically change sent status.

## 34.5 Correction and publication

- Published result cannot be edited in place.
- New publication supersedes the previous publication.
- Trader receives a correction notification.
- Old publication/evidence remains visible to authorized internal users.
- Overpayment is blocked from normal paid completion.

## 34.6 Accessibility

- Core Admin workflows are keyboard-operable.
- Core Trader flows are screen-reader navigable.
- Status is not color-only.
- Crop viewer has non-drag controls.
- Dialog focus is managed correctly.
- RTL and LTR mixed identifiers are readable and copy correctly.

---

# 35. Implementation Order

Recommended frontend order:

1. Semantic design tokens, Persian typography foundation, RTL shell.
2. Typed API client, auth/session, error handling, ETag, idempotency utilities.
3. Shared amount, IBAN, date, status, warning, and confirmation components.
4. Trader login, account state, dashboard, navigation.
5. Trader beneficiary and Payment Request draft/revision/submit flow.
6. Admin shell, role navigation, work queue primitives.
7. Accountant Payment Request review.
8. Batch preview, draft version, finalization.
9. Manager exact-version approval.
10. Preview/final export and mark-sent flow.
11. File upload and authorized preview foundation.
12. Bank Result split workspace.
13. Manual crop and Receipt Segment lifecycle.
14. Payment Attempt confirmation and retry/correction.
15. Publication and Trader result/dispute flows.
16. Gold-sale, incoming-payment, statement import, and dispatch flows.
17. Reports, audit, bank configuration, operational health views.
18. Accessibility, responsive, performance, and security hardening.

---

# 36. Decisions Still Requiring Formal Approval

The following do not invalidate the UI baseline but must be finalized before production release:

1. Exact authentication mechanism and recovery flow.
2. Recent-authentication method and validity duration for manager approval.
3. Whether text-only paid confirmation is allowed, and under which role/policy.
4. Exact Persian status labels and product terminology.
5. Exact brand identity, logo, font family, and final token values.
6. Default trader amount-input unit and whether users may change it per request.
7. Trader-facing IBAN masking policy.
8. Maximum file sizes and supported production formats.
9. Exact evidence requirement for publication.
10. Strong-control requirement for correcting an already published Paid result.
11. Final Phase 1A share-card format.
12. Approved initial bank templates and source accounts.

Recommended baseline decisions already reflected in this document:

- trader amount input supports explicit Toman/IRR selection;
- manager approval is always at exact Batch Version level;
- minimal internal rectangular crop is Phase 1A;
- automatic segmentation is not Phase 1A;
- trader and admin are separate frontend applications;
- SaaS/multi-company UI is Phase 4.

---

# 37. Coding Agent Rules

1. Do not copy messaging-app or spreadsheet UI as the product structure.
2. Do not put manager approval on Payment Request screens.
3. Do not let the manager approve a mutable Batch.
4. Do not label a preview export as sendable.
5. Do not mark a Batch sent merely because a file was downloaded.
6. Do not publish a Receipt Segment directly without a Publication record.
7. Do not edit an active Publication in place.
8. Do not delete replaced financial evidence from normal UI.
9. Do not hide amount units.
10. Do not use floating-point arithmetic for money.
11. Do not store long-lived auth secrets in insecure browser storage.
12. Do not expose storage keys or permanent object URLs.
13. Do not expose full mixed bank bundles to traders.
14. Do not make manual crop dependent on AI/OCR.
15. Do not automatically retry a financial command with a new idempotency key.
16. Do not overwrite stale records after an ETag conflict.
17. Do not rely on color alone for status.
18. Do not include sensitive banking values in analytics or URLs.
19. Do not let frontend permissions replace backend checks.
20. Do not implement future Phase 4 tenancy UI in Phase 1A.

---

# 38. Final Status

This specification is the authoritative product-level UI/UX baseline for implementing the Trader PWA and Admin Web App against documents `00` through `06` version 1.1.

The UI direction is:

```text
Luxury minimal + professional FinTech
Persian-first and RTL
Mobile-first Trader PWA
Desktop-first Admin Web App
Queue-driven accountant operations
Exact-version manager approval
Strong financial confirmations
Phase 1A internal manual crop
Immutable publication and correction history
Manual-first operation without AI dependency
```

The next document to review is:

```text
08_Bank_File_and_Result_Processing.md
```

It must be aligned with the exact Batch Version, Bank Export, file lifecycle, statement import run, Receipt Segment, manual crop, candidate match, confirmed evidence, and publication workflows defined in versions 1.1 of documents `00` through `07`.
