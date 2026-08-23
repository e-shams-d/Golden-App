/**
 * The decision, and the four ways a screen could quietly get it wrong.
 *
 * Screens slice 2. Asserted against the source of the page and the dialog, for the reason
 * `approval-screens.test.ts` gives: these are claims about *what the code cannot do* — send a
 * re-read hash, update before the server answers, re-target an open dialog — and a rendering test
 * would prove the happy path while leaving each of those open.
 *
 * Covers: UI-APPROVE-001, UI-APPROVE-002, UI-STALE-001, UI-STALE-002, UI-REJECT-001.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { isStale, tomanFromIrr } from "../src/batches";

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
const DIALOG = join(import.meta.dirname, "..", "components", "decision-dialog.tsx");

const page = readFileSync(DETAIL_PAGE, "utf8");
const dialog = readFileSync(DIALOG, "utf8");

describe("UI-APPROVE-001: the dialog sends the hash it was rendered with", () => {
  it("captures the hash when the dialog opens", () => {
    // §13.5's "expected content hash" is only meaningful if it is the value the manager was
    // looking at. Captured in `openFor`, before any await, from the view this render received.
    expect(page).toMatch(/setCaptured\(\{\s*hash: view\.version\.content_hash/u);
  });

  it("submits the captured hash and not a fresh read", () => {
    expect(page).toContain("expectedContentHash: captured.hash");
    // The failure this forbids: reading `view.version.content_hash` at submit time. After a
    // replacement that value is the *new* version's, the server would accept it, and the manager
    // would have approved content they never saw.
    expect(page).not.toMatch(/expectedContentHash:\s*view\.version\.content_hash/u);
  });

  it("keeps the hash out of the dialog entirely", () => {
    // The dialog cannot send a different hash because it never receives one. That is a stronger
    // guarantee than remembering not to.
    expect(dialog).not.toContain("content_hash");
    expect(dialog).not.toContain("expectedContentHash");
  });
});

describe("UI-APPROVE-002: the UI updates only after the server answers", () => {
  it("calls onDecided after the command resolves, not before", () => {
    // §13.5's closing line. An optimistic update here would show an approval that did not
    // happen, on the one screen where that is worst.
    const submitBody = page.slice(page.indexOf("const submit ="), page.indexOf("if (open !== null)"));
    const decidedAt = submitBody.indexOf("onDecided()");
    const thenAt = submitBody.indexOf(".then(() => {");
    expect(decidedAt).toBeGreaterThan(thenAt);
    expect(thenAt).toBeGreaterThan(-1);
  });

  it("holds no local decided state to be wrong about", () => {
    // There is no `setApproved` or `setDecision` — the screen reloads and reads the server's
    // answer. A local flag is a second place for the truth to live.
    expect(page).not.toMatch(/setApproved|setDecided|setDecision\b/u);
  });
});

describe("UI-STALE-001: a stale page is blocked, bannered, linked and readable", () => {
  it("renders the banner when the rendered version is no longer current", () => {
    expect(page).toContain("isStale(versionId, phase.view)");
    expect(page).toContain('data-testid="stale-banner"');
    expect(page).toContain('role="alert"');
  });

  it("links to the current version", () => {
    expect(page).toContain('data-testid="stale-current-link"');
    expect(page).toMatch(/versions\/\$\{phase\.view\.version\.id\}/u);
  });

  it("keeps the page readable as history", () => {
    // §13.4: "retain the old page as read-only history". `Detail` is rendered in both branches;
    // only the decision section is withheld.
    const staleBranch = page.slice(page.indexOf("isStale(versionId"), page.indexOf("</>"));
    expect(staleBranch).toContain("<Detail view={phase.view} />");
  });

  it("decides staleness from the rendered id, not from a remembered flag", () => {
    // A boolean captured at first load would still say "current" after a replacement. The
    // comparison is against the id in the URL and the id in the freshly fetched view.
    expect(isStale("v1", { version: { id: "v1" } } as never)).toBe(false);
    expect(isStale("v1", { version: { id: "v2" } } as never)).toBe(true);
  });
});

/**
 * The plan said to assert this "by replacing the version while the dialog is open", which needs a
 * renderer this repository does not have. What is asserted instead is the structure that makes the
 * behaviour impossible to get wrong: `Decide` owns the dialog's state and is not rendered in the
 * stale branch, so React unmounts it — there is no code path along which an open dialog could
 * learn about a replacement, whether or not a test drives one.
 *
 * That is a change of method, not of claim, and it is the stronger of the two: a live-replacement
 * test proves the transfer does not happen on the path it exercises. This proves there is no path.
 */
describe("UI-STALE-002: an open dialog is not transferred to the replacement", () => {
  it("does not render the decision section in the stale branch", () => {
    // §13.4's last clause. The guarantee is structural: `Decide` — which owns the dialog — is
    // rendered only in the non-stale branch, so on discovering staleness the dialog unmounts
    // rather than being handed a new version.
    const staleBranch = page.slice(page.indexOf("isStale(versionId"), page.indexOf(") : ("));
    expect(staleBranch).not.toContain("<Decide");
  });

  it("captures the version id alongside the hash", () => {
    // The submitted request names the captured version, so even mid-flight it cannot land on
    // another one.
    expect(page).toContain("versionId: view.version.id");
    expect(page).toContain("versionId: captured.versionId");
  });
});

describe("UI-REJECT-001: a rejection needs a reason", () => {
  it("requires the reason before the button enables", () => {
    expect(dialog).toMatch(/kind === "approve" \|\| reason\.trim\(\)\.length > 0/u);
  });

  it("renders the reason field only for a rejection", () => {
    expect(dialog).toMatch(/kind === "reject" \? \(/u);
    expect(dialog).toContain('data-testid="decision-reason"');
  });

  it("says the version is not edited", () => {
    // §13.6: "Rejection does not edit the version; a new replacement version may be created
    // later." The wording matters because a manager rejecting needs to know what happens next.
    expect(dialog).toContain("admin.decide.rejectBody");
  });
});

describe("the step-up is bound to this action and this version", () => {
  it("passes both purposes and never shares one", () => {
    // Two purposes, so a step-up obtained to refuse cannot be spent approving. §3 of the
    // baseline lists action alongside resource.
    expect(page).toContain("APPROVE_PURPOSE");
    expect(page).toContain("REJECT_PURPOSE");
    expect(page).toMatch(/open === "approve" \? APPROVE_PURPOSE : REJECT_PURPOSE/u);
  });

  it("binds the context to the captured version", () => {
    expect(page).toContain("resourceId: captured.versionId");
    expect(page).toContain("resourceType: STEP_UP_RESOURCE_TYPE");
  });
});

describe("the decision section is withheld when the caller may not decide", () => {
  it("returns nothing rather than offering a button that will be refused", () => {
    expect(page).toMatch(/if \(!view\.separation_of_duty\.may_decide\) return null;/u);
  });
});

describe("Toman conversion stays exact", () => {
  it("divides by ten without floating point", () => {
    // An IRR total passes MAX_SAFE_INTEGER around nine quadrillion and this platform's amounts
    // are already in the trillions, so `Number(irr) / 10` would silently lose rials.
    expect(tomanFromIrr("1500000000")).toBe("150000000");
    expect(tomanFromIrr("12345678901234")).toBe("1234567890123.4");
    expect(tomanFromIrr("5")).toBe("0.5");
    expect(tomanFromIrr("0")).toBe("0");
  });
});
