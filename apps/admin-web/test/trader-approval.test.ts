import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The friction in front of an irreversible approval.
 *
 * Approving a gold trader is audited, it is what lets that business create payment
 * requests, and `trader_lifecycle` has no transition from `approved` back to
 * `pending_approval`. During the local acceptance pass a stray click approved a test
 * business and nothing could undo it.
 *
 * **The asymmetry was inside one screen.** Rejecting on the same row needs a typed reason
 * and the server enforces it; approving sent `POST /traders/{id}/approve` from the first
 * click. Both decisions are equally final.
 *
 * Structural assertions, like the sibling precondition suite, and for the same reason: the
 * behavioural version needs a rendered DOM and a server, and the thing being guarded here
 * is that the code keeps a shape — a second step exists, and the first button no longer
 * calls the command.
 *
 * Covers: F-9.
 */

const PAGE = join(import.meta.dirname, "..", "app", "traders", "page.tsx");

const read = (): string => readFileSync(PAGE, "utf8");

/** The file without comments: a note explaining the rule must not satisfy the rule. */
const code = (): string =>
  read()
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/^\s*\/\/.*$/gm, "");

describe("approving a trader", () => {
  it("has a second step", () => {
    expect(code()).toContain('data-testid="trader-approve-confirm"');
    expect(code()).toContain('data-testid="trader-approve-yes"');
  });

  it("names the business in the question", () => {
    // A table row is identified by its position, and position is what a misplaced click
    // gets wrong. A confirmation that says only "are you sure?" re-asks the question the
    // operator already answered wrongly.
    const source = code();
    const confirmation = source.slice(
      source.indexOf('data-testid="trader-approve-confirm"'),
      source.indexOf('data-testid="trader-approve-yes"'),
    );
    expect(confirmation).toContain("trader.display_name");
  });

  it("does not approve from the first click", () => {
    // The guard that makes the two above mean anything. A confirmation rendered beside a
    // button that still submits is decoration.
    const source = code();
    const approveCalls = source.match(/decide\(trader, "approve"\)/g) ?? [];
    expect(approveCalls).toHaveLength(1);

    const confirmIndex = source.indexOf('data-testid="trader-approve-confirm"');
    expect(confirmIndex).toBeGreaterThan(-1);
    expect(source.indexOf('decide(trader, "approve")')).toBeGreaterThan(confirmIndex);
  });

  it("still rejects in one step, because rejecting already asks for a reason", () => {
    // Not an oversight to be tidied up later. The reason field is the friction on that
    // half, the server refuses a rejection without one, and adding a second confirmation
    // on top would be friction for its own sake.
    const source = code();
    expect(source).toContain('decide(trader, "reject")');
    expect(source).not.toContain('data-testid="trader-reject-confirm"');
  });
});
