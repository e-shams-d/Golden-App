/**
 * The correction dialog: the one place in this application that asks for somebody else's password.
 *
 * M0 slice A2. `tests/backend/test_result_screens_exist.py` checks that the dialog exists and
 * names its fields; this checks the two properties that make it *safe*, which are properties of
 * the order things happen in rather than of the markup:
 *
 * - the approver's step-up is obtained and spent in one flow, never cached;
 * - the id sent as `approved_by_admin_user_id` is the one the step-up route resolved, never a
 *   second lookup of the same username.
 *
 * Asserted on source for the reason `approval-screens.test.ts` gives: the claim is about
 * completeness and ordering, and rendering it would need a browser, a router and a stubbed
 * transport to say something the source already says plainly. The a11y sweep opens the page for
 * real.
 *
 * Covers: UI-CORRECTION-001, UI-CORRECTION-002.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const APP_ROOT = join(import.meta.dirname, "..");
const DIALOG = join(APP_ROOT, "components", "correction-dialog.tsx");
const PAGE = join(APP_ROOT, "app", "requests", "[requestId]", "publication", "page.tsx");
const RESULTS = join(APP_ROOT, "src", "payment-results.ts");
const AUTH = join(APP_ROOT, "src", "auth.ts");

const read = (path: string): string => readFileSync(path, "utf8");

describe("the correction dialog", () => {
  it("asks for the approver's credentials rather than the caller's", () => {
    const source = read(DIALOG);

    expect(source).toContain("correction-approver-username");
    expect(source).toContain("correction-approver-password");

    // `new-password`, not `current-password`. The browser must not offer the signed-in person's
    // saved credential for a field that belongs to somebody else — they would submit their own
    // and be refused, and the refusal says nothing about why.
    expect(source).toContain('autoComplete="new-password"');
    expect(source).not.toContain('autoComplete="current-password"');
  });

  it("does not offer the segment that is already published", () => {
    const source = read(DIALOG);

    // The server refuses a correction back onto the published segment —
    // `uq_evidence_link_attempt_segment_type` refuses a second link for a pair that already has
    // one — so offering it would be offering a choice that always fails.
    expect(source).toContain("segments.filter((segment) => segment.id !== currentSegmentId)");
  });

  it("requires every field and an explicit confirmation before it will submit", () => {
    const source = read(DIALOG);
    const ready = source.slice(source.indexOf("const ready ="), source.indexOf("return ("));

    for (const field of [
      "segmentId.length > 0",
      "reason.trim().length > 0",
      "approverUsername.trim().length > 0",
      "approverPassword.length > 0",
      "confirmed",
    ]) {
      expect(ready).toContain(field);
    }
  });
});

describe("the correction flow", () => {
  it("spends the step-up immediately instead of holding one", () => {
    const source = read(PAGE);
    const submit = source.slice(source.indexOf("const submitCorrection"));

    // The step-up call and the command in one chain. A context obtained earlier — on dialog open,
    // say — would expire while the person typed, and a cached one is something the server refuses
    // the second time because it is single-use.
    const stepUp = submit.indexOf("approverReauthenticate({");
    const command = submit.indexOf("correctPublication(");
    expect(stepUp).toBeGreaterThan(-1);
    expect(command).toBeGreaterThan(stepUp);
    expect(submit).not.toContain("useState<");
  });

  it("names the approver the step-up resolved, not a second lookup", () => {
    const source = read(PAGE);
    const submit = source.slice(source.indexOf("const submitCorrection"));

    // The id comes off the step-up response. Resolving the username twice is how the id in the
    // body and the id the context was bound to come to disagree — and the server compares them,
    // so the failure would be a refusal nobody could explain.
    expect(submit).toContain("approvedByAdminUserId: context.approverId");
  });

  it("binds the step-up to the publication being superseded", () => {
    const source = read(PAGE);
    const submit = source.slice(source.indexOf("const submitCorrection"));

    // Not the request. A context taken while looking at version 3 must not correct version 4,
    // which is the binding the batch approval uses one aggregate along.
    expect(submit).toContain("resourceId: active.id");
    expect(submit).toContain("resourceType: CORRECTION_RESOURCE_TYPE");
  });

  it("sends the recent-auth token for the correction and for nothing else", () => {
    const source = read(RESULTS);

    expect(source.match(/recentAuthToken/g)).toHaveLength(1);
    const correction = source.slice(source.indexOf("export async function correctPublication"));
    expect(correction).toContain("recentAuthToken");
  });

  it("keeps the approver's step-up out of the session holder's auth adapter", () => {
    const source = read(AUTH);

    // `adminAuthAdapter`'s contract is "the signed-in person". A method on it that checked
    // somebody else's password would sit beside `reauthenticate` with a near-identical signature,
    // and the difference between them is the entire security property.
    const adapter = source.slice(
      source.indexOf("export const adminAuthAdapter"),
      source.indexOf("export async function approverReauthenticate"),
    );
    expect(adapter).not.toContain("approverReauthenticate");
    expect(source).toContain("export async function approverReauthenticate");
  });
});
