/**
 * The bank configuration screens, and the four claims that make them safe to ship.
 *
 * M0 slice B. `tests/backend/test_every_operation_has_a_screen.py` proves the six operations are
 * *reached*; this proves they are reached **correctly**, which is a different question and the one
 * a reachability gate cannot answer.
 *
 * Asserted on source for the reason `approval-screens.test.ts` gives: these are claims about
 * completeness and about what is absent, and rendering them would need a browser, a router and a
 * stubbed transport to say what the source says plainly. The a11y sweep opens both pages for real.
 *
 * Covers: UI-BANKCFG-001, UI-BANKCFG-002.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const APP_ROOT = join(import.meta.dirname, "..");
const LIST = join(APP_ROOT, "app", "bank-configuration", "page.tsx");
const DETAIL = join(APP_ROOT, "app", "bank-configuration", "[profileId]", "page.tsx");
const DATA = join(APP_ROOT, "src", "bank-configuration.ts");

const read = (path: string): string => readFileSync(path, "utf8");

/**
 * The file with its comments removed.
 *
 * **Needed because the first version of this suite failed on a sentence explaining why the screen
 * does not do the thing.** The detail page's docstring contains the words `status === "active"` in
 * a paragraph saying it deliberately avoids that, and a substring assertion cannot tell prose from
 * code. `test_governance_counts_reconcile.py` records the identical trap: its own note about a
 * defect matched the pattern looking for the defect.
 *
 * So assertions about what a screen *does not* do read this, and assertions about what it *says*
 * read the raw source.
 */
const code = (path: string): string =>
  read(path)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

describe("the bank configuration data module", () => {
  it("sends no precondition and no idempotency key with the activation", () => {
    const source = read(DATA);
    const activate = source.slice(source.indexOf("export async function activateBankProfileVersion"));

    // `bank_profile_versions` has no `record_version` — a version is superseded by inserting a new
    // row, never edited — so there is nothing for an `If-Match` to be stale against, and
    // `command_catalog.yaml` asks for a server-side lock. The route accepts neither header.
    expect(activate).not.toContain("ifMatch");
    expect(activate).not.toContain("idempotencyKey");
    expect(activate).not.toContain("rv-");
  });

  it("never turns a rial figure into a number on the way out", () => {
    const source = read(DATA);

    // The read types carry limits as `string | null`. `MONEY_TIME_CONTRACT.md` rule 9 forbids
    // JavaScript `Number` for monetary values, and a type that said `number` would have made every
    // screen below parse one.
    expect(source).toContain("default_transfer_limit_irr: string | null");
    expect(source).toContain("after_cutoff_transfer_limit_irr: string | null");

    // Exactly one conversion exists, in the create path, because the request model takes integers.
    // A second would mean some read had started parsing.
    expect(source.match(/Number\(/g)).toHaveLength(1);
  });

  it("sends null rather than zero for a limit a bank does not publish", () => {
    const source = read(DATA);

    // The column is null-tolerant because the two mean different things: null is "no published
    // limit", zero would mean every transfer must be split into nothing.
    const helper = source.slice(source.indexOf("function digitsOrNull"));
    expect(helper).toContain('trimmed === "" ? null');
  });
});

describe("the bank configuration screens", () => {
  it("reads which version is in force from the profile pointer, not by scanning statuses", () => {
    const source = read(DETAIL);

    // `current_version_id` and the version rows must agree — `20260816_0014` moves them in one
    // transaction. A screen that searched the list for `status === "active"` would present its own
    // second opinion as fact, and the disagreement is exactly what an operator needs to see.
    expect(source).toContain("phase.profile.current_version_id");
    expect(code(DETAIL)).not.toMatch(/status\s*===\s*["']active["']/);
  });

  it("offers no way to edit a version", () => {
    const source = read(DETAIL);

    // A `bank_profile_version` is immutable: the runtime's UPDATE grant covers `status` alone. A
    // form offering to change a limit would be offering something the database refuses.
    expect(code(DETAIL)).not.toContain("PATCH");
    expect(code(DETAIL)).not.toContain("updateVersion");
    // And it says why the "new version" path is absent rather than leaving a blank space.
    expect(source).toContain("bank.newVersionBlocked");
  });

  it("makes the activation a two-step confirmation", () => {
    const source = read(DETAIL);

    // No undo: superseding a version means activating another one, and every payment built
    // afterwards is shaped by the one in force.
    expect(source).toContain("bank-activate-confirm");
    expect(source).toContain("bank.activateConfirm");
  });

  it("does not offer to activate the version that is already in force", () => {
    const source = read(DETAIL);

    expect(source).toContain("version.id === phase.profile.current_version_id");
    expect(source).toContain("bank.alreadyInForce");
  });

  it("tells a person that creating a profile creates its first version too", () => {
    const source = read(LIST);

    // The command does two things and looks like one; the transaction is what makes that safe, and
    // a screen that did not say so would leave somebody hunting for a second form.
    expect(source).toContain("bank.newProfileHint");
  });

  it("renders the account identifier the server sent, masked or not", () => {
    const source = read(LIST);

    // POL-003 has not settled who sees a full IBAN. The server masks according to permission; a
    // screen that unmasked locally would decide an open question.
    expect(source).toContain("account.normalized_iban");
    expect(source).not.toContain("slice(-4)");
    expect(source).not.toContain("****");
  });
});
