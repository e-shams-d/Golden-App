/**
 * The approval screens render what §13.2 and §13.3 specify — parsed, not transcribed.
 *
 * Screens slice 1. `tests/backend/test_approval_read_shape.py` parses the same two sections to
 * check the API carries every field. **This file parses them again to check the screen renders
 * every label**, and that is deliberate: two copies of "the nineteen mandatory fields" would
 * disagree the day the document gained a twentieth, and neither copy would say which.
 *
 * The assertion is on the *source* of the two page components rather than on a rendered DOM.
 * Rendering would be stronger, and it would also need a browser, a router and a stubbed
 * transport for a claim that is really about completeness — every specified field has a label on
 * the page. The a11y sweep opens both pages for real; this checks nothing was left out.
 *
 * Covers: UI-APPROVAL-001, UI-APPROVAL-002, UI-APPROVAL-003.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { adminNavigation } from "../src/navigation";

/**
 * The navigation entries a holder of these permissions would see.
 *
 * Filtered here rather than imported, because `src/navigation.ts` exports the declarative list
 * and the shell does the filtering. `test/navigation-permissions.test.ts` widens the same const
 * for the same reason: the dashboard entry carries no `permission` key at all, so the union's
 * `item.permission` is a type error without a widening.
 */
function visibleTo(held: readonly string[]): readonly string[] {
  const items: readonly { href: string; permission?: string }[] = adminNavigation;
  return items
    .filter((item) => item.permission === undefined || held.includes(item.permission))
    .map((item) => item.href);
}

const REPOSITORY_ROOT = join(import.meta.dirname, "..", "..", "..");
const SPECIFICATION = join(
  REPOSITORY_ROOT,
  "Implementation Docs",
  "04_Frontend_and_Experience",
  "21_UI_Design_System_and_Screen_Specification.md",
);

const QUEUE_PAGE = join(import.meta.dirname, "..", "app", "batches", "page.tsx");
const DETAIL_PAGE = join(
  import.meta.dirname,
  "..",
  "app",
  "batches",
  "[batchId]",
  "versions",
  "[versionId]",
  "page.tsx",
);

/** The bullet list under a heading in the specification. */
function bulleted(heading: string): readonly string[] {
  const text = readFileSync(SPECIFICATION, "utf8");
  const start = text.indexOf(heading);
  const end = text.indexOf("\n## ", start + heading.length);
  return text
    .slice(start, end)
    .split("\n")
    .filter((line) => line.startsWith("- "))
    .map((line) => line.slice(2).trim().replace(/[;.]$/u, "").toLowerCase());
}

/**
 * Each specified field, mapped to the message key whose label carries it.
 *
 * The mapping is what a human gets right; the *list* comes from the document, so a field added
 * there fails the completeness check below rather than being quietly unmapped. Identical in shape
 * to the backend's mapping, and for the same reason.
 */
const QUEUE_LABELS: Readonly<Record<string, string>> = {
  "batch reference": "batch_number",
  version: "admin.batches.versionLabel",
  total: "admin.batches.total",
  "row count": "admin.batches.rowCount",
  bank: "admin.batches.bank",
  "source account": "admin.batches.sourceAccount",
  "mapping version": "admin.batches.mappingVersion",
  "warning count": "admin.batches.warningCount",
  "prepared/finalized by": "admin.batches.preparedBy",
  age: "admin.batches.age",
};

const DETAIL_LABELS: Readonly<Record<string, string>> = {
  "batch reference": "admin.approval.batchReference",
  "exact version": "admin.approval.exactVersion",
  "immutable status": "admin.approval.immutableStatus",
  "total irr and toman equivalent": "admin.approval.totalToman",
  "request count": "admin.approval.requestCount",
  "attempt/row count": "admin.approval.rowCount",
  "trader count": "admin.approval.traderCount",
  "beneficiary count": "admin.approval.beneficiaryCount",
  "bank profile version": "admin.approval.bankProfileVersion",
  "mapping version": "admin.approval.mappingVersion",
  "source account": "admin.approval.sourceAccount",
  "content hash fingerprint": "admin.approval.fingerprint",
  "ordered rows": "admin.approval.rows",
  warnings: "admin.approval.warnings",
  "non-sendable preview export if available": "admin.approval.preview",
  "finalizer identity": "admin.approval.finalizedBy",
  "separation-of-duty status": "separation-of-duty",
};

describe("the specification is still readable", () => {
  it("lists ten queue columns and seventeen detail fields", () => {
    // The control. A parser returning nothing would make every assertion below vacuous while
    // reporting success — the failure shape this repository has been caught by more than once.
    expect(bulleted("## 13.2 Approval queue")).toHaveLength(10);
    expect(bulleted("## 13.3 Approval detail")).toHaveLength(17);
  });
});

describe("UI-APPROVAL-001: the detail renders every mandatory field", () => {
  const source = readFileSync(DETAIL_PAGE, "utf8");

  for (const [field, marker] of Object.entries(DETAIL_LABELS)) {
    it(`renders ${field}`, () => {
      expect(source).toContain(marker);
    });
  }

  it("maps every field the specification names", () => {
    // The corpus check. Without it, a field added to §13.3 would never be tested, because the
    // loop above iterates the *mapping*.
    const specified = bulleted("## 13.3 Approval detail");
    const unmapped = specified.filter((field) => !(field in DETAIL_LABELS));
    expect(unmapped).toEqual([]);
  });
});

describe("UI-APPROVAL-002: the queue identifies the exact version", () => {
  const source = readFileSync(QUEUE_PAGE, "utf8");

  it("renders a version number in every row", () => {
    // §13.2's opening sentence: "Each row must identify the exact version, not only the logical
    // batch." A row showing a batch reference alone is the defect that sentence exists to
    // prevent, and it would look completely reasonable.
    expect(source).toContain("admin.batches.versionLabel");
    expect(source).toContain('data-testid="version-number"');
  });

  it("links to the version, not to the batch", () => {
    // The link is where the mistake would actually bite: a link to `/batches/{id}` would open
    // whatever version is current, which after a replacement is not the one the row described.
    expect(source).toContain("/versions/${row.version_id}");
  });

  for (const [column, marker] of Object.entries(QUEUE_LABELS)) {
    it(`renders ${column}`, () => {
      expect(source).toContain(marker);
    });
  }

  it("maps every column the specification names", () => {
    const specified = bulleted("## 13.2 Approval queue");
    const unmapped = specified.filter((column) => !(column in QUEUE_LABELS));
    expect(unmapped).toEqual([]);
  });
});

describe("UI-APPROVAL-003: the queue is behind the approval-view permission", () => {
  it("is absent for somebody without it", () => {
    expect(visibleTo(["payment_request.read"])).not.toContain("/batches");
  });

  it("is present for somebody with it", () => {
    expect(visibleTo(["payment_batch_version.read_approval_view"])).toContain("/batches");
  });

  it("is gated on the read, not on the approve", () => {
    // `read_approval_view` goes to accountant, manager and read_only_auditor; `.approve` to
    // manager alone. Gating on the stronger grant would hide the screen from two of the three
    // roles that have a reason to open it — an auditor seeing what was decided, and an
    // accountant checking their own work.
    expect(visibleTo(["payment_batch_version.read_approval_view"])).toContain("/batches");
    expect(visibleTo(["payment_batch_version.approve"])).not.toContain("/batches");
  });
});

describe("the separation-of-duty status comes from the server", () => {
  const source = readFileSync(DETAIL_PAGE, "utf8");

  it("renders what the API decided and computes nothing", () => {
    // A client-side comparison would be a second opinion about a rule the database enforces, and
    // the two would eventually disagree. The screen reads `separation_of_duty` and never looks
    // at who is signed in.
    expect(source).toContain("view.separation_of_duty.may_decide");
    expect(source).toContain("view.separation_of_duty.reason");
    expect(source).not.toContain("actor_id");
    expect(source).not.toContain("currentUser");
  });

  it("shows the reason, not only the verdict", () => {
    // "You cannot approve this" with no remedy sends somebody to ask a colleague. The two
    // refusals have different answers and the reason is what distinguishes them.
    expect(source).toContain("admin.approval.mayNotDecide");
    expect(source).toMatch(/separation_of_duty\.reason\s*\?/u);
  });
});
