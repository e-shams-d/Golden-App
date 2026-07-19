# Gold Trade Settlement Platform
# Client Packaging and Distribution Guide

**Document ID:** `19_Client_Packaging_and_Distribution_Guide`  
**Version:** `1.1`  
**Status:** `Authoritative Packaging and Client Distribution Baseline`  
**Language:** English  
**Primary audience:** Frontend engineers, release engineers, mobile/desktop packaging engineers, security reviewers, QA engineers, operations maintainers, coding agents  
**Authority:** This document governs client packaging, installation, distribution, signing, update, compatibility, and release-channel rules. It must not override domain, workflow, security, API, or production-operation rules defined in documents `00` through `18` version `1.1`.

**Depends on:**

- `00_Master_Implementation_Blueprint.md`
- `01_Product_Requirements_PRD.md`
- `03_System_Architecture.md`
- `05_API_Specification.md`
- `06_Workflows_and_State_Machines.md`
- `07_UI_UX_Specification.md`
- `11_Frontend_Implementation_Guide.md`
- `12_Security_RBAC_Audit.md`
- `13_DevOps_Deployment_Operations.md`
- `14_Testing_QA_Acceptance.md`
- `15_Agent_Implementation_Plan.md`
- `16_Implementation_Documentation_Index.md`
- `17_Future_Phases_Roadmap_and_Backlog.md`
- `18_Production_Setup_and_Runbook.md`

---

## 1. Purpose

This document defines how the two client applications of the Gold Trade Settlement Platform are built, packaged, installed, distributed, updated, supported, and retired across browser, PWA, Android, and Windows delivery channels.

The platform has two independent frontend applications:

```text
Trader PWA
    Mobile-first
    Persian/RTL
    Owned-trader scope only

Admin Web Application
    Desktop-first
    Persian/RTL
    Accountant, manager, warehouse, audit and administration workflows
```

The backend API and server-side business rules remain authoritative regardless of packaging method.

Android and Windows packages are optional delivery wrappers. They are not separate products, do not contain separate financial logic, and are not required for Phase 1A.

This document is intended to prevent the following implementation failures:

- packaging Admin and Trader functionality into one client bundle;
- creating native-only business logic that diverges from the web platform;
- caching sensitive financial information for offline use;
- embedding secrets or production credentials in packages;
- distributing unsigned or unverifiable builds;
- allowing old clients to silently operate against incompatible APIs;
- treating installation packaging as a substitute for server-side security;
- forcing Android or Windows packaging into Phase 1A without demonstrated business value.

---

## 2. Fixed Packaging Decisions

### 2.1 Phase 1A delivery baseline

Phase 1A must deliver:

```text
Trader application:
    Responsive browser application
    Installable PWA where supported

Admin application:
    Desktop browser application
    Browser-managed PWA installation may be supported

Backend:
    Server-deployed API and private file services
```

Phase 1A does not require:

- Android APK or AAB;
- Google Play or local-marketplace publication;
- Windows MSI or EXE installer;
- Electron;
- Tauri;
- Capacitor;
- native camera APIs;
- native push notifications;
- offline financial submission;
- device-local financial databases.

### 2.2 Two-application rule

The Trader and Admin applications must remain separate build and deployment artifacts.

```text
apps/trader-pwa
apps/admin-web
```

They must have independent:

- package names;
- build pipelines;
- runtime configuration;
- route trees;
- manifests where applicable;
- service-worker policies;
- release verification;
- deployment health checks;
- security review;
- optional wrapper identities.

An Admin route must not be shipped inside the Trader PWA and merely hidden through CSS, navigation, or client-side permission checks.

### 2.3 Server-authoritative rule

Every client, including any future Android or Windows wrapper, must use the same backend commands, permissions, ownership checks, state-machine guards, idempotency rules, and audit requirements.

Packaging must never introduce:

```text
Native-only approval
Native-only payment confirmation
Native-only evidence confirmation
Native-only status transition
Direct database access
Direct private-storage access
Separate bank-export logic
Separate money calculation rules
```

### 2.4 Packaging is not an offline architecture

Installing a PWA or wrapper does not authorize offline financial processing.

The following actions are always online, server-authoritative commands:

- submit or correct a payment request;
- finalize a batch version;
- approve or reject a batch version;
- generate a final bank export;
- mark a bank export as sent;
- confirm an attempt as paid or failed;
- create or replace a confirmed evidence link;
- publish or correct a trader result;
- confirm incoming payment;
- authorize gold dispatch;
- change permissions or retention policy.

---

## 3. Client and Delivery Matrix

| Client | Primary users | Phase 1A delivery | Optional later delivery | Packaging authority |
|---|---|---|---|---|
| Trader PWA | Gold traders | Mobile browser and installable PWA | Android TWA; Capacitor only for approved native needs | This document + Frontend/Security specs |
| Admin Web | Accountant, manager, warehouse, authorized admins | Desktop browser | Browser-installed PWA; Tauri only when justified | This document + Frontend/Security specs |
| Android wrapper | Primarily traders | Not required | TWA first; Capacitor only after ADR | Separate packaging release approval |
| Windows wrapper | Admin staff | Not required | Browser PWA first; Tauri only after ADR | Separate packaging release approval |
| Backend API | All clients indirectly | Server deployment only | Same contract for all approved clients | API and Backend specs |

---

## 4. Architecture of Packaged Clients

### 4.1 Source-of-truth architecture

```text
                         +----------------------+
                         |   Backend API        |
                         | auth/RBAC/workflows  |
                         +----------+-----------+
                                    |
                    HTTPS + versioned API contract
                                    |
              +---------------------+---------------------+
              |                                           |
     +--------v---------+                       +---------v--------+
     | Trader PWA       |                       | Admin Web        |
     | separate build   |                       | separate build   |
     +--------+---------+                       +---------+--------+
              |                                           |
     optional Android TWA                         optional Windows PWA
     optional Capacitor                           optional Tauri
```

### 4.2 Shared packages

The two applications may share controlled packages such as:

```text
packages/api-client
packages/auth-client
packages/domain-contracts
packages/design-system
packages/financial-ui
packages/file-ui
packages/localization
packages/validation
packages/observability
```

Shared packages must not collapse application boundaries.

The Trader build must not import Admin pages, admin command handlers, admin navigation, or privileged file viewers.

### 4.3 Wrapper responsibility

A wrapper may provide:

- app icon and launch surface;
- trusted navigation to the approved hosted origin;
- limited native share or file-picker integration;
- operating-system installation and update metadata;
- secure wrapper-level diagnostics;
- approved deep-link routing.

A wrapper must not provide:

- independent financial state;
- hidden API credentials;
- a local authoritative database;
- locally trusted permission decisions;
- bypasses for recent authentication;
- unapproved background submission;
- direct bank integration.

---

## 5. Phase Boundaries

### 5.1 Phase 1A — Web and PWA baseline

Required:

- Trader mobile-browser support;
- Trader PWA manifest and installability where supported;
- Admin desktop-browser support;
- secure HTTPS deployment;
- controlled service-worker caching;
- update detection;
- explicit offline state;
- no sensitive offline cache;
- release/build information;
- cross-browser QA on approved browser versions.

### 5.2 Phase 1B — Optional delivery convenience

May include after a separate business decision:

- Android Trusted Web Activity for the Trader PWA;
- private or controlled Android distribution;
- improved PWA install guidance;
- approved Web Share enhancements;
- packaging telemetry that does not contain financial data.

Phase 1B packaging must not be coupled to Phase 1B AI functionality. An Android wrapper is a delivery decision, not an AI requirement.

### 5.3 Phase 2 — Approved native capabilities

May include only when web capability is insufficient:

- Capacitor for approved camera/file/share functionality;
- Tauri for an approved Windows installer;
- signed automatic updates for a desktop wrapper;
- managed-device policies;
- stronger device posture signals as advisory controls.

### 5.4 Phase 3 and later

May include:

- managed enterprise distribution;
- store distribution;
- native push notifications;
- device-binding controls;
- mobile device management integration;
- advanced wrapper observability;
- controlled public API companion clients.

No future phase may remove the browser/manual fallback merely because a wrapper exists.

---

## 6. Trader PWA Requirements

### 6.1 Trader-only manifest

The Trader PWA must have its own manifest.

Minimum properties:

```json
{
  "id": "/",
  "name": "<approved Persian product name>",
  "short_name": "<approved short name>",
  "start_url": "/",
  "scope": "/",
  "display": "standalone",
  "dir": "rtl",
  "lang": "fa-IR",
  "theme_color": "<approved semantic token>",
  "background_color": "<approved semantic token>",
  "icons": []
}
```

Brand values and icons must come from the approved brand package. Placeholder product names, icons, or colors must not be shipped to production.

### 6.2 Manifest rules

The manifest must:

- use the Trader origin and scope only;
- not route to the Admin origin;
- use versioned and cache-controlled icons;
- include maskable icons where supported;
- use a stable application identifier;
- avoid permissions or shortcuts that expose sensitive information;
- be tested after reverse-proxy deployment;
- remain accessible through HTTPS.

### 6.3 Install prompt behavior

Install guidance must be optional and non-blocking.

The application must remain fully usable in a supported browser without installation.

Install prompts must not:

- repeatedly interrupt the user;
- imply that installation makes the application more secure;
- hide browser-only fallback instructions;
- appear during a financial confirmation dialog;
- appear while an upload or financial command is pending.

### 6.4 Admin installability

The Admin application may be installed through browser PWA support for operator convenience, but this is not a requirement.

If Admin PWA installability is enabled, it must use:

- a separate manifest;
- a separate icon and application name identifying the Admin application;
- a separate scope and origin;
- a stricter service-worker policy;
- no offline access to authenticated pages or financial data.

---

## 7. Service Worker and Cache Policy

### 7.1 Default security posture

The service worker is a delivery optimization, not a data store.

The default policy is:

```text
Static public assets      → cacheable with versioning
Public app shell          → limited cache allowed
Authenticated HTML        → network-first or network-only
Financial API responses   → network-only
Private files/evidence    → network-only
Financial commands        → network-only, never queued
```

### 7.2 Cache allowlist

The service worker may cache:

- hashed JavaScript and CSS assets;
- approved public icons;
- approved public fonts;
- public localization resources;
- a non-sensitive offline shell;
- public error/help content specifically approved for caching.

### 7.3 Cache denylist

The service worker must not cache:

- payment requests or revisions;
- beneficiaries or IBAN values;
- trader profile data;
- payment attempts;
- batch versions or approvals;
- bank exports;
- bank-result bundles;
- bank statement rows;
- receipt segments;
- evidence images;
- publications or share files containing financial data;
- audit data;
- authentication or CSRF tokens;
- API error payloads containing sensitive context;
- Admin HTML responses containing user-specific information.

### 7.4 Request-method policy

Only safe, explicitly allowlisted `GET` resources may be cached.

The service worker must never queue, replay, synthesize, or retry financial `POST`, `PUT`, `PATCH`, or `DELETE` requests.

Background Sync must not be used for financial commands in Phase 1A.

### 7.5 Cache-key safety

Cache keys must not include raw:

- tokens;
- IBANs;
- trader names;
- beneficiary names;
- payment references;
- signed file URLs;
- query strings containing financial identifiers.

### 7.6 Logout and session revocation

On logout or detected session revocation:

- user-scoped in-memory state must be cleared;
- client query caches must be cleared;
- any mistakenly cached authenticated data must be purged;
- no financial data may remain available through back navigation while offline;
- the application must return to an unauthenticated state.

### 7.7 Offline page

The offline page must display only non-sensitive content:

```text
The connection is unavailable.
Financial actions cannot be completed offline.
Reconnect and retry from the latest server state.
```

The offline page must not show stale financial records.

---

## 8. Client Storage Policy

### 8.1 Prohibited persistent storage

The following must not be stored in `localStorage`, IndexedDB, Cache Storage, or wrapper preferences:

- long-lived authentication tokens;
- passwords;
- session secrets;
- full API responses containing financial data;
- IBANs and beneficiary snapshots;
- bank files or evidence;
- financial command payloads;
- idempotency payload bodies;
- audit records;
- raw AI/OCR outputs;
- private file URLs.

### 8.2 Allowed limited storage

Allowed examples, subject to security review:

- non-sensitive theme or language preference;
- dismissed onboarding prompts;
- PWA install-prompt state;
- public build/version metadata;
- non-sensitive accessibility preference.

### 8.3 Native secure storage

If a future Capacitor or Tauri wrapper requires native credential material, the exact authentication design must be approved through an ADR.

Secure storage is not automatically safe merely because it uses an operating-system key store. The design must address:

- revocation;
- session binding;
- device loss;
- backup extraction;
- rooted or compromised devices;
- application reinstall;
- logout cleanup;
- multi-user devices;
- support recovery.

No native wrapper may invent a token-storage strategy independently of the authentication authority document.

---

## 9. Authentication and Session Compatibility

### 9.1 Browser and PWA

Browser and installed-PWA clients must use the approved web authentication architecture.

Required controls include:

- revocable session;
- secure transport;
- secure cookie behavior where cookie sessions are chosen;
- CSRF protection when required;
- session-expiry handling;
- recent authentication for sensitive actions;
- account-status revalidation;
- explicit logout.

### 9.2 Trusted Web Activity

A TWA loads the approved web origin and should reuse the same web authentication behavior.

Before release, verify:

- correct origin and scope;
- Digital Asset Links validation;
- no fallback to an untrusted origin;
- expected cookie/session behavior;
- logout and revocation behavior;
- deep links cannot escape the allowlisted origin;
- certificate and domain renewal procedures.

### 9.3 Embedded WebView wrappers

Capacitor or Tauri WebView behavior can differ from a normal browser.

Before adopting an embedded WebView, an ADR must cover:

- cookie and SameSite behavior;
- CSRF design;
- origin and custom-scheme behavior;
- navigation allowlists;
- popup/external-link handling;
- file upload/download behavior;
- private file viewing;
- session revocation;
- update policy;
- platform security support lifetime.

### 9.4 Recent authentication

A wrapper must not weaken recent-authentication requirements.

Biometric unlock of a wrapper is not automatically equivalent to server-approved recent authentication.

Any biometric or device credential integration must map to an explicitly approved assurance flow and must not approve a financial command by itself.

---

## 10. Android Delivery Strategy

### 10.1 Preferred order

```text
1. Mobile browser
2. Installed Trader PWA
3. Trusted Web Activity
4. Capacitor only for approved native requirements
```

### 10.2 Trusted Web Activity suitability

TWA is suitable when:

- the Trader PWA is already production-ready;
- no separate native screens are needed;
- the approved hosted origin remains the source of UI and logic;
- Digital Asset Links can be maintained;
- the organization can protect the signing key;
- update and support responsibilities are assigned.

### 10.3 TWA requirements

A production TWA release requires:

- approved package identifier;
- approved application name and icons;
- immutable release version and increasing build number;
- production signing key;
- protected signing process;
- `assetlinks.json` on the exact production origin;
- verified origin relationship;
- tested browser fallback behavior;
- tested installation and upgrade;
- documented distribution channel;
- checksum and release manifest;
- rollback/support plan.

### 10.4 Android package identity

The package identifier must be stable and channel-specific where necessary.

Example pattern:

```text
ir.<company>.<product>.trader
ir.<company>.<product>.trader.staging
```

Staging and production packages must not share confusing names or icons.

### 10.5 Android signing

The production signing key is a high-value operational asset.

Required controls:

- generate once through an approved process;
- store outside the source repository;
- limit access to authorized release personnel or CI identity;
- back up securely in a separate protected location;
- record ownership and recovery procedure;
- never print passwords or key material in CI logs;
- use release signing only for production artifacts;
- verify the signer certificate before distribution;
- document implications of key loss or compromise.

### 10.6 Direct APK distribution

Direct APK distribution may be used only through an approved channel.

The distribution page or process must provide:

- exact application and channel name;
- version and build number;
- release date;
- SHA-256 checksum;
- signer fingerprint where operationally appropriate;
- release notes;
- minimum supported Android version;
- installation and update instructions;
- warning against unofficial mirrors;
- support contact/process.

Do not distribute debug builds or unsigned APKs.

### 10.7 Store or marketplace distribution

Before publishing to any store or marketplace:

- review current marketplace rules;
- confirm data-safety/privacy declarations;
- confirm account ownership;
- confirm signing ownership;
- verify screenshots contain no real financial data;
- verify support and privacy-policy links;
- test staged rollout and update behavior;
- define emergency removal and replacement procedures.

### 10.8 Capacitor adoption gate

Capacitor is allowed only when a documented requirement cannot be met safely through the browser/PWA/TWA approach.

Potential justified requirements:

- controlled native camera capture;
- approved native file picker behavior;
- approved native share integration;
- managed push notification support;
- managed-device integration.

Capacitor adoption requires:

- architecture ADR;
- security review;
- permission matrix;
- WebView navigation allowlist;
- native plugin inventory;
- dependency and vulnerability policy;
- update and support policy;
- wrapper-specific QA;
- proof that manual/browser fallback remains available.

---

## 11. Windows Delivery Strategy

### 11.1 Preferred order

```text
1. Supported desktop browser
2. Browser-installed Admin PWA
3. Tauri wrapper only after approved business need
4. Electron only after explicit architecture approval
```

### 11.2 Browser installation

For most Phase 1A Admin users, browser installation is sufficient:

- install from a supported browser;
- pin to Start or taskbar;
- preserve server-delivered updates;
- avoid maintaining an additional installer;
- retain normal browser security updates.

### 11.3 Tauri adoption gate

A Tauri wrapper may be justified when:

- the client formally requires an MSI or EXE;
- browser installation is operationally unacceptable;
- a controlled native capability is required;
- Windows code signing and update operations can be maintained;
- the security team approves WebView and updater behavior.

Tauri adoption requires:

- ADR and owner;
- stable application identifier;
- signed installer;
- navigation allowlist;
- restricted command/API surface;
- no shell-command execution from document content;
- secure updater design;
- upgrade and rollback tests;
- supported Windows-version policy;
- vulnerability update process.

### 11.4 Electron policy

Electron is not the default choice.

It may be considered only when:

- a required capability cannot be met safely with browser PWA or Tauri;
- the team can maintain Chromium/Electron security updates;
- installer size and memory overhead are accepted;
- a formal security and lifecycle review is completed.

### 11.5 Windows code signing

When organizational policy requires signing, production Windows installers and update packages must be signed with an approved certificate.

Controls must cover:

- certificate custody;
- timestamping where applicable;
- signer identity verification;
- expiration and renewal;
- revocation procedure;
- CI access;
- artifact hash verification;
- archival of signed artifacts.

### 11.6 Windows update behavior

A desktop wrapper updater must:

- verify signed update metadata and artifacts;
- use HTTPS;
- reject invalid or downgraded metadata;
- support staged rollout;
- preserve application data rules;
- not bypass backend compatibility checks;
- provide a recovery path if update fails;
- never download executable updates from document-supplied URLs.

---

## 12. Navigation, Deep Links, and Origin Controls

### 12.1 Allowlisted origins

Packaged clients must navigate only to explicitly approved origins.

At minimum:

```text
Trader client → Trader origin and approved public support origins
Admin client  → Admin origin and approved support origins
API calls     → Approved API origin
```

### 12.2 Untrusted links

External links must open through a controlled external-browser flow where appropriate.

Document content, user notes, uploaded files, OCR output, or API data must never be allowed to instruct the wrapper to:

- navigate to arbitrary origins;
- download executable files;
- invoke native commands;
- open local files;
- access custom URI handlers;
- bypass TLS validation.

### 12.3 Deep-link validation

Deep links must:

- use an allowlisted scheme/host/path;
- validate identifiers server-side;
- re-check authentication and ownership;
- avoid embedding sensitive financial data in URLs;
- avoid authorizing commands through link navigation;
- not bypass recent authentication.

---

## 13. Native Permissions

### 13.1 Least privilege

A package must request only permissions required by an approved feature.

Examples:

| Permission/capability | Default | Allowed only when |
|---|---:|---|
| Internet | Required | Client communicates with approved HTTPS services |
| Camera | Denied | Approved capture workflow exists |
| Photos/files | Denied | Approved upload/download workflow requires it |
| Notifications | Denied | Notification feature and privacy policy are approved |
| Location | Denied | No Phase 1A use case |
| Contacts | Denied | No approved use case |
| Microphone | Denied | No approved use case |
| Background execution | Denied | Explicit later-phase requirement and review |

### 13.2 Permission denial

The application must remain usable through a documented fallback when optional permissions are denied.

No financial command may depend on granting an unrelated device permission.

---

## 14. Build and Release Provenance

### 14.1 Build once, promote the same artifact

Packaging artifacts must follow the same release discipline as server images:

```text
Source commit
→ controlled build
→ test and scan
→ sign
→ archive immutable artifact
→ deploy to staging/pilot
→ approve exact artifact
→ distribute exact artifact to production
```

A production package must not be rebuilt after staging approval.

### 14.2 Release manifest

Every client release must have a machine-readable manifest containing at least:

```json
{
  "product_version": "<version>",
  "client": "trader-pwa|admin-web|android-trader|windows-admin",
  "channel": "dev|staging|pilot|production",
  "git_commit": "<commit>",
  "build_id": "<build-id>",
  "build_time_utc": "<timestamp>",
  "artifact_sha256": "<hash>",
  "signer_reference": "<non-secret reference>",
  "api_contract_version": "<version>",
  "minimum_backend_version": "<version>",
  "maximum_tested_backend_version": "<version>",
  "pwa_manifest_hash": "<hash-or-null>",
  "service_worker_version": "<version-or-null>"
}
```

### 14.3 Required archived artifacts

Depending on delivery type, archive:

- web build metadata;
- PWA manifest and service-worker build identifier;
- APK/AAB;
- Android signer certificate fingerprint;
- MSI/EXE or other Windows installer;
- signed update metadata;
- checksums;
- SBOM or dependency inventory;
- vulnerability-scan result;
- release notes;
- known issues;
- compatibility matrix;
- QA evidence;
- approval record.

### 14.4 Artifact naming

Artifact names must identify:

- client;
- version;
- build number;
- channel;
- architecture where applicable.

Example:

```text
gold-trader-1.3.0+10300-production.apk
gold-admin-1.3.0+20300-production-x64.msi
```

Do not expose customer names, bank information, or secrets in artifact names.

---

## 15. Versioning and Compatibility

### 15.1 Product and build versions

The product may use semantic versioning, but phase names must not be encoded as an irreversible compatibility assumption.

Recommended fields:

```text
Product version: MAJOR.MINOR.PATCH
Build number: monotonically increasing per package identity
Release ID: immutable internal identifier
```

### 15.2 Independent client versions

The Trader PWA, Admin Web, Android wrapper, and Windows wrapper may have different build numbers while belonging to the same product release.

Example:

```text
Product release: 1.4.0
Trader web build: trader-web-842
Admin web build: admin-web-615
Android wrapper: versionCode 10400
Windows wrapper: installer build 20400
```

### 15.3 Backend compatibility

Every packaged release must declare its tested backend compatibility range.

The client must handle an incompatible backend response explicitly rather than failing silently.

Possible server response behavior:

```text
Client too old:
    block sensitive commands
    show approved update instruction
    preserve access to support/logout

Client newer than supported backend:
    block incompatible feature
    show deployment mismatch message
```

A minimum-version policy must not unexpectedly lock users out of historical records without an incident/support path.

### 15.4 API contract

Generated API clients must be based on the approved OpenAPI contract.

Packaging must not freeze an obsolete hand-written API client into native code without compatibility testing.

---

## 16. Release Channels and Environment Separation

### 16.1 Standard channels

| Channel | Purpose | Data policy | Distribution |
|---|---|---|---|
| `dev` | Developer testing | Synthetic only | Internal |
| `staging` | Integration and QA | Synthetic/redacted | QA users |
| `pilot` | Limited approved real use | Production-governed | Named pilot users |
| `production` | General approved use | Production | Approved channel |

### 16.2 Channel separation

Channels should use separate:

- origins;
- package identifiers where simultaneous installation is needed;
- application names/icons;
- signing/release metadata;
- API endpoints;
- telemetry environments;
- crash-report projects;
- user accounts and datasets.

A staging package must not connect to the production API.

### 16.3 Visual identification

Non-production packages must be clearly identifiable through:

- application name;
- icon badge;
- persistent environment banner;
- version/system-information page.

Do not use production colors and names without an environment marker for staging packages.

---

## 17. Web and PWA Build Pipeline

### 17.1 Separate builds

The build pipeline must build each application separately.

Example logical sequence:

```bash
npm ci
npm run lint
npm run typecheck
npm run test
npm run generate:api
npm run build:trader
npm run build:admin
```

The actual repository commands may differ, but the outputs must remain independent.

### 17.2 Web build gates

A web/PWA artifact is releasable only when:

- lint and TypeScript checks pass;
- OpenAPI generation/compatibility passes;
- unit/component tests pass;
- PWA manifest validation passes;
- service-worker cache-policy tests pass;
- both application builds pass;
- secret scan passes;
- dependency scan passes;
- accessibility smoke tests pass;
- browser E2E tests pass;
- release metadata is generated.

### 17.3 No client secrets

Build-time public configuration must be explicitly allowlisted.

The build must fail if frontend bundles contain patterns matching:

- database credentials;
- Redis credentials;
- storage credentials;
- session signing secrets;
- AI provider keys;
- backup credentials;
- private certificates;
- server-only environment variables.

### 17.4 Source maps

Source-map publication must follow an approved policy.

If source maps are uploaded to a private error-monitoring provider:

- they must not be publicly served;
- the provider must be approved;
- release IDs must match;
- no secrets or source-embedded credentials may exist;
- retention must be controlled.

---

## 18. Android Build Pipeline

### 18.1 Preconditions

Before building a production Android artifact:

- the exact web release is approved;
- the production PWA is deployed and healthy;
- manifest and origin are final;
- Digital Asset Links are verified;
- package identifier is approved;
- signing key access is approved;
- version code is greater than prior releases;
- QA device matrix is defined;
- privacy/support metadata is ready.

### 18.2 Controlled build

The build should run in an approved CI runner or controlled build workstation.

The pipeline must:

- use locked dependencies;
- generate release metadata;
- build release artifact;
- sign artifact;
- verify signature;
- calculate SHA-256;
- scan dependency/artifact where tooling supports it;
- archive artifact and manifest;
- publish only after approval.

### 18.3 Digital Asset Links deployment

`assetlinks.json` must be treated as production configuration.

Changes require:

- review of package name;
- review of signer fingerprint;
- staging verification;
- production verification;
- change record;
- rollback plan.

### 18.4 Android update tests

Test at least:

- clean install;
- update from minimum supported version;
- update from current production version;
- logout before and after update;
- active session behavior;
- revoked session behavior;
- file upload/download;
- share flow;
- deep links;
- offline behavior;
- installation from approved channel;
- signature mismatch rejection.

---

## 19. Windows Build Pipeline

### 19.1 Preconditions

Before building a Windows wrapper:

- business requirement is approved;
- wrapper ADR is approved;
- supported Windows versions are defined;
- WebView/runtime requirements are defined;
- application identifier is stable;
- code-signing process is approved;
- updater behavior is approved;
- navigation allowlist is implemented;
- QA VM matrix exists.

### 19.2 Controlled build

The build must run on a controlled Windows runner or approved compatible environment.

Required outputs:

- signed installer;
- artifact checksum;
- signer information;
- dependency/SBOM report;
- release manifest;
- installation/uninstallation test evidence;
- update test evidence;
- known limitations.

### 19.3 Windows installation tests

Test:

- clean supported Windows VM;
- standard user installation where intended;
- administrator installation where required;
- install path permissions;
- Start menu/taskbar entry;
- URL/deep-link behavior;
- secure update;
- uninstall;
- reinstall;
- old-version upgrade;
- blocked unsigned or tampered update;
- corporate proxy behavior if in scope.

---

## 20. Update Strategy

### 20.1 PWA/web updates

PWA updates are delivered by deploying approved frontend artifacts.

Rules:

- hashed static assets must be immutable;
- HTML and release metadata must use appropriate revalidation;
- service-worker versions must be explicit;
- old and new assets must coexist during rollout when required;
- an update must not interrupt an in-flight financial command;
- the user must not unknowingly submit stale data after an incompatible update;
- critical updates may require reload after the current command resolves;
- update prompts must identify that the latest server state will be reloaded.

### 20.2 Stale-client handling

The frontend should compare its build metadata with server compatibility information.

For a stale but compatible client:

- show a non-blocking update notice;
- reload at a safe point.

For an incompatible client:

- block sensitive commands;
- preserve logout and support access;
- explain the update requirement;
- avoid automatic replay of pending commands.

### 20.3 Android updates

For each Android release:

- increase version code;
- sign with the approved key;
- test upgrade paths;
- use staged rollout where supported;
- monitor crash/login/update issues;
- retain the previous approved artifact;
- document emergency replacement procedure.

### 20.4 Windows updates

For a Windows wrapper:

- sign installer and update metadata;
- test upgrade and rollback/reinstall;
- maintain compatibility with the backend;
- avoid silent forced restarts during financial work;
- provide approved release notes;
- retain prior artifacts and compatibility information.

### 20.5 Forced updates

Forced updates are reserved for:

- critical security fixes;
- revoked signing or trust material;
- API incompatibility that cannot be safely supported;
- severe data-integrity defects.

A forced update decision requires an owner, incident/change reference, support plan, and communication plan.

---

## 21. Rollback and Recovery

### 21.1 Web rollback

Web rollback must deploy the previously approved immutable frontend artifact or digest.

Do not rebuild old source and assume it is identical.

Before rollback, verify:

- backend compatibility;
- service-worker behavior;
- cached asset availability;
- API contract compatibility;
- database migration impact;
- active incident scope.

### 21.2 Wrapper rollback

Mobile and desktop packages cannot always be downgraded automatically.

The recovery plan may include:

- stop further rollout;
- re-publish previous compatible release where channel permits;
- issue a fixed higher-version release;
- disable affected optional functionality server-side;
- preserve browser/PWA fallback;
- communicate support steps.

### 21.3 Signing compromise

If a signing key or certificate is suspected compromised:

- stop distribution;
- revoke or disable affected release channel where possible;
- preserve evidence;
- identify affected versions;
- rotate according to platform capability;
- issue a new approved release path;
- notify users through approved channels;
- record the incident and post-incident review.

---

## 22. Distribution Security

### 22.1 Approved distribution sources

Users must receive packages only from approved sources such as:

- approved organization download portal;
- approved marketplace/store account;
- approved managed-device channel;
- controlled support delivery process.

### 22.2 Download portal requirements

A direct-download portal must:

- use HTTPS;
- identify production vs staging clearly;
- display version/build/channel;
- display checksum;
- provide release notes;
- avoid directory listing;
- prevent unauthorized replacement of artifacts;
- log administrative publication changes;
- not include sensitive user data.

### 22.3 Artifact verification

Release operators must verify:

- checksum;
- signature;
- release manifest;
- expected package identity;
- expected channel;
- expected origin/API configuration.

### 22.4 No email or messenger attachment as authoritative distribution

Sending an APK or installer as an unverified messenger/email attachment must not be the authoritative production distribution method.

An approved support message may link users to the verified distribution source.

---

## 23. Privacy, Telemetry, and Crash Reporting

### 23.1 Data minimization

Client telemetry must not contain:

- full names where avoidable;
- IBANs;
- payment amounts as labels;
- bank tracking numbers;
- evidence content;
- bank files;
- access tokens;
- passwords;
- raw financial API payloads;
- document OCR content.

### 23.2 Allowed operational metadata

Subject to approved policy, telemetry may include:

- release/build ID;
- client type;
- channel;
- operating-system version;
- browser/WebView version;
- generic route identifier;
- error category;
- correlation ID that is safe for support use;
- performance timing without sensitive labels.

### 23.3 Third-party SDKs

No third-party analytics, advertising, tracking, keyboard, file, or crash-reporting SDK may be added without:

- security review;
- privacy review;
- data-flow documentation;
- vendor approval;
- configuration review;
- retention review;
- opt-out/consent decision where applicable.

Advertising SDKs are out of scope.

---

## 24. Browser and Device Support Policy

### 24.1 Supported browser matrix

The project must define and test a supported browser matrix for:

- Android Chrome or approved Chromium-based browser;
- desktop Chrome/Edge or other approved browser;
- installed PWA mode;
- minimum viewport and device class.

The exact versions are release-time operational decisions and must be recorded in the support policy.

### 24.2 Unsupported clients

Unsupported or obsolete clients must receive:

- a clear message;
- safe update instructions;
- no partial execution of financial commands;
- support fallback.

### 24.3 Rooted, jailbroken, or compromised devices

Device posture may be used as an advisory risk signal in a later phase.

It must not be assumed to be perfectly detectable.

Any blocking policy requires an ADR, false-positive analysis, user-support process, and browser fallback decision.

---

## 25. Accessibility, RTL, and Localization Packaging QA

Every packaged form of the application must preserve:

- Persian-first UI;
- RTL layout and navigation;
- correct numeric alignment;
- readable IRR/Toman presentation;
- correct Jalali display where required;
- keyboard access for Admin workflows;
- screen-reader labels;
- touch-target sizes for Trader mobile flows;
- zoom and text scaling;
- reduced-motion behavior;
- visible environment and update messages.

Native wrappers must not introduce platform chrome or dialogs that reverse layout meaning, truncate Persian text, or obscure financial confirmation context.

---

## 26. File Upload, Download, and Share Behavior

### 26.1 Upload

Packaged clients must use the same authorized upload API and file lifecycle as the web application.

They must not:

- upload directly to private storage without approved signed-upload flow;
- bypass type/size validation;
- rename executable files to accepted extensions;
- retain private files in application cache beyond required temporary use;
- retry a completed financial attachment command with a new idempotency key after an uncertain response.

### 26.2 Download

Private files must be downloaded or previewed only after server authorization.

Signed URLs, if used, must be short-lived and scoped.

A wrapper must not convert a temporary signed URL into a permanent bookmark or cache entry.

### 26.3 Share

Only an approved trader-visible `PaymentResultPublication` or approved share artifact may be shared.

The client must not share:

- the original mixed bank-result bundle;
- internal receipt segments not approved for publication;
- accountant notes;
- manager approval details;
- other traders' information;
- raw API payloads.

Share-sheet integration must use an approved derived file or safe text summary.

---

## 27. PWA and Packaged-Client QA Matrix

### 27.1 Trader PWA tests

Test at minimum:

1. Open the production-like Trader origin in a supported mobile browser.
2. Confirm Admin routes and assets are absent from the Trader bundle.
3. Log in with a test trader.
4. Install the PWA.
5. Reopen from the home screen.
6. Verify session expiry and revocation.
7. Create and submit a payment request using synthetic/UAT data.
8. Verify IRR/Toman handling without floating-point loss.
9. Upload an approved test file.
10. View an approved publication.
11. Share only the approved publication artifact.
12. Log out and confirm sensitive state is cleared.
13. Disconnect network and confirm no financial data is exposed offline.
14. Attempt an offline command and confirm it is blocked.
15. Deploy a compatible update and verify update prompt behavior.
16. Deploy an incompatible test build and verify safe blocking.

### 27.2 Admin browser/PWA tests

Test at minimum:

1. Open the Admin origin in a supported desktop browser.
2. Confirm Trader-only routing and ownership behavior remain separate.
3. Log in as accountant.
4. Verify queue and split-view behavior.
5. Verify manual crop interaction and file preview.
6. Verify ETag conflict handling.
7. Verify idempotency recovery after simulated timeout.
8. Verify sensitive pages are unavailable offline.
9. Log in as manager in a separate authorized test session.
10. Verify exact-version approval with recent authentication.
11. Verify stale approval is blocked.
12. Verify logout clears local query state.
13. Verify service worker does not cache private files or API results.

### 27.3 Android TWA tests

Test:

- signer and package identity;
- Digital Asset Links;
- trusted full-screen origin;
- fallback when verification fails;
- session and logout;
- deep links;
- file upload/download/share;
- update from prior approved release;
- offline restrictions;
- staging/production separation;
- tampered artifact rejection.

### 27.4 Capacitor tests

In addition to normal client tests:

- WebView origin policy;
- plugin permission review;
- secure storage cleanup;
- external-navigation handling;
- native file/camera behavior;
- session revocation;
- background behavior;
- dependency vulnerability scan;
- native bridge input validation.

### 27.5 Windows PWA/Tauri tests

Test:

- install on clean supported Windows VM;
- application identity and channel;
- code signature where applicable;
- WebView/runtime behavior;
- session and recent authentication;
- upload/download/manual crop;
- update and rollback/recovery;
- uninstall/reinstall;
- navigation allowlist;
- no shell/native command from untrusted content;
- no private file persistence after logout.

### 27.6 Production smoke-test restriction

Packaging smoke tests in production must not create real financial requests, approve batches, generate final exports, confirm payments, or publish results unless a formally approved production fixture and procedure exists.

Full financial packaging E2E tests run in staging/UAT.

---

## 28. Release Acceptance Gates

### 28.1 Web/PWA release gate

A web/PWA release is acceptable only when:

- separate Trader and Admin builds are verified;
- PWA manifest and service-worker policies pass;
- no sensitive offline cache exists;
- authentication/session tests pass;
- backend compatibility is declared;
- browser E2E tests pass;
- accessibility and RTL checks pass;
- artifact manifest and checksums exist;
- release is deployed from the approved immutable build;
- production smoke checks pass safely.

### 28.2 Android release gate

An Android package is acceptable only when:

- business need is approved;
- package identity is final;
- signing key custody is approved;
- signature is verified;
- Digital Asset Links works;
- update path is tested;
- staging and production are separated;
- no client secret exists;
- security/privacy review passes;
- browser/PWA fallback remains available;
- distribution source is approved.

### 28.3 Windows wrapper release gate

A Windows wrapper is acceptable only when:

- wrapper ADR is approved;
- browser PWA has been evaluated first;
- supported Windows versions are defined;
- code signing policy is satisfied;
- secure updater is tested;
- navigation/native-command surface is reviewed;
- installation, upgrade, uninstall, and recovery tests pass;
- backend compatibility is declared;
- production distribution channel is approved.

---

## 29. Operational Support Requirements

### 29.1 System information screen

Each client must provide a safe support view containing:

- product version;
- build ID;
- client type;
- channel;
- API contract version;
- service-worker or wrapper version;
- correlation/support identifier;
- last successful server contact time;
- update status.

It must not display secrets, tokens, full internal URLs, or sensitive financial records.

### 29.2 Support diagnostics

Diagnostics export, if implemented, must be explicit and privacy-reviewed.

It may include:

- generic environment information;
- release metadata;
- recent error categories;
- safe correlation IDs.

It must not include:

- passwords or tokens;
- full API payloads;
- bank files;
- evidence images;
- IBANs;
- financial command bodies.

### 29.3 End-of-support policy

For each packaged client, document:

- minimum supported operating-system/browser version;
- minimum supported wrapper version;
- notice period where possible;
- update instructions;
- fallback path;
- support owner.

---

## 30. Open Decisions and Required ADRs

The following decisions remain open until approved:

| ADR/decision | Required before |
|---|---|
| Final brand name, icons and font licensing | Production PWA/package |
| Supported browser and OS matrix | UAT |
| Android package identifier | Android build |
| Android distribution channel | Android pilot |
| Android signing-key owner and recovery | Android production |
| Whether TWA provides sufficient value | Android implementation |
| Capacitor native-capability justification | Capacitor implementation |
| Windows installer business requirement | Tauri/Electron work |
| Windows code-signing and updater policy | Windows production |
| Authentication behavior in embedded WebView | Capacitor/Tauri adoption |
| Wrapper telemetry/crash provider | Any wrapper release |
| Minimum-client-version enforcement policy | Production update system |
| Screenshot/screen-recording policy | Native wrapper security review |
| Managed-device or device-binding policy | Later phase |

No coding agent may resolve these by embedding an irreversible choice without an ADR.

---

## 31. Coding-Agent Rules

A coding agent implementing packaging must follow these rules:

1. Do not merge Trader and Admin applications into one build.
2. Do not place Admin routes in the Trader package.
3. Do not treat Android or Windows packaging as required Phase 1A work.
4. Do not add native business rules or financial state transitions.
5. Do not embed API keys, server secrets, credentials, certificates, or private endpoints.
6. Do not store sensitive financial API responses offline.
7. Do not implement offline approval, confirmation, publication, or dispatch.
8. Do not cache bank files, evidence, publications, or authenticated Admin pages in a service worker.
9. Do not add Background Sync for financial commands.
10. Do not bypass backend RBAC, ownership, ETag, idempotency, or recent-authentication controls.
11. Do not use a generic WebView with unrestricted navigation.
12. Do not allow document or OCR content to invoke native commands or external URLs.
13. Do not use debug Android signing for real users.
14. Do not publish unsigned or unverifiable production artifacts.
15. Do not rebuild a package after staging approval; promote the exact artifact.
16. Do not hard-code production domains in shared business modules.
17. Do not add analytics or crash SDKs without privacy/security review.
18. Do not expose source maps publicly.
19. Do not force update during an unresolved financial command.
20. Do not remove the browser/PWA fallback when introducing a wrapper.

---

## 32. Implementation Work Breakdown

### 32.1 Phase 1A packaging tasks

```text
PKG-WEB-001  Separate Trader/Admin build outputs
PKG-PWA-001  Trader manifest and icons
PKG-PWA-002  Service-worker allowlist/denylist
PKG-PWA-003  Offline shell and network-only financial routes
PKG-PWA-004  Install guidance
PKG-REL-001  Client release manifest
PKG-REL-002  Build/version system-information view
PKG-QA-001   PWA cache and offline security tests
PKG-QA-002   Browser install/update tests
PKG-OPS-001  Web artifact archive and rollback reference
```

### 32.2 Optional Android tasks

```text
PKG-AND-001  Android packaging ADR
PKG-AND-002  Package identity and channel plan
PKG-AND-003  Signing-key custody procedure
PKG-AND-004  TWA/Bubblewrap project
PKG-AND-005  Digital Asset Links deployment
PKG-AND-006  Signed CI build and verification
PKG-AND-007  Direct/store distribution procedure
PKG-AND-008  Install/upgrade/security QA
```

### 32.3 Optional Windows tasks

```text
PKG-WIN-001  Windows packaging ADR
PKG-WIN-002  Browser PWA operational evaluation
PKG-WIN-003  Tauri security architecture
PKG-WIN-004  Code-signing procedure
PKG-WIN-005  Signed installer pipeline
PKG-WIN-006  Secure updater
PKG-WIN-007  Clean-VM install/upgrade/uninstall QA
```

---

## 33. Definition of Done

### 33.1 PWA packaging Definition of Done

PWA packaging is complete when:

- Trader and Admin remain independent applications;
- Trader manifest is valid and production-branded;
- service-worker policy is tested;
- sensitive resources are network-only;
- no financial command is queued offline;
- install and update flows work;
- logout clears client state;
- release manifest and build information exist;
- browser compatibility tests pass;
- rollback uses an archived approved artifact.

### 33.2 Android packaging Definition of Done

Android packaging is complete when:

- business/architecture approval exists;
- package and signer identities are final;
- signing key is protected and recoverable;
- Digital Asset Links is validated;
- production artifact is signed and hashed;
- update path passes;
- distribution source is approved;
- no secrets or separate financial logic exist;
- PWA fallback remains available;
- QA and release evidence are archived.

### 33.3 Windows packaging Definition of Done

Windows packaging is complete when:

- browser PWA alternative was evaluated;
- wrapper ADR exists;
- installer and updater are signed as required;
- native command/navigation surfaces are restricted;
- installation, update, uninstall and recovery pass;
- supported Windows policy is documented;
- no secrets or separate financial logic exist;
- QA and release evidence are archived.

---

## 34. Final Packaging Strategy

The approved strategy is:

```text
Phase 1A
    Trader: mobile browser + installable PWA
    Admin: desktop browser, optional browser-installed PWA

Phase 1B+
    Android TWA only when installation creates proven business value

Phase 2+
    Capacitor or Tauri only for approved native requirements

All phases
    Same server-authoritative business rules
    Separate Trader and Admin applications
    No sensitive offline financial cache
    Signed and traceable artifacts
    Browser/manual fallback preserved
```

Packaging is successful when it improves access and distribution without changing financial authority, weakening security, duplicating business logic, or creating an additional source of truth.

---

## 35. Change Log

### Version 1.1

- aligned the guide to the two-frontend architecture;
- made browser/PWA the only required Phase 1A delivery;
- separated Trader and Admin manifests, builds and security surfaces;
- added strict service-worker and client-storage rules;
- added session/WebView compatibility requirements;
- added TWA, Capacitor and Tauri adoption gates;
- added signing-key and code-signing governance;
- added immutable artifact promotion and release manifests;
- added client/backend compatibility policy;
- added safe update, forced-update and rollback procedures;
- added origin, deep-link and native-command restrictions;
- added privacy, telemetry and third-party SDK controls;
- added packaging QA and release gates;
- added ADR register and coding-agent prohibitions.
