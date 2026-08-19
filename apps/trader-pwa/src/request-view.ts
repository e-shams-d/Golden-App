/**
 * The decisions the request screens make, as functions rather than as JSX.
 *
 * This repository has no jsdom and no testing-library — the frontend suites are vitest over
 * source and filesystem, with real rendering proved by Playwright in `tests/a11y` and
 * `tests/demo`. So a claim like "the correction screen shows the reviewer's note" is only
 * testable in CI if the deciding is separable from the drawing. These three functions are
 * that separation: each is the whole of a screen's judgement about what to show, and each
 * has a test that would fail if the judgement changed.
 *
 * The drawing is still the screens'. What is here is only what could otherwise be asserted
 * by grepping JSX, which is a test of a string rather than of a behaviour.
 */

import type { EnteredAmount, PaymentRequest, Revision } from "./payment-requests";

/**
 * What the trader must be told before they can act, or `null` when there is nothing.
 *
 * `UI-REQ-001` in one function: a request returned without the reason visible is a request
 * the trader resubmits unchanged. The note is shown whenever the server sent one, and not
 * only in `needs_trader_correction` — the accountant's note on a request they marked eligible
 * is also something its owner is entitled to read, and hiding it on a status check would mean
 * a screen that decides for itself which of the centre's messages the trader may see.
 */
export function correctionNotice(request: PaymentRequest): string | null {
  const note = request.review_note?.trim();
  return note ? note : null;
}

export type RevisionRow = Readonly<{ revision: Revision; isCurrent: boolean }>;

/**
 * Every revision, in the order given, with the current one marked.
 *
 * `UI-REQ-002`. Two properties matter and both are asserted by its test: nothing is dropped —
 * a history that silently omitted a revision would defeat the one thing the history exists
 * for — and the current one is distinguishable from its predecessors, which is what makes
 * "what did I submit the first time" answerable rather than merely stored.
 *
 * The order is the server's, not re-sorted here. The backend orders by `revision_number`
 * rather than `created_at`, because two revisions written in the same second would otherwise
 * read in an order nobody chose; re-sorting in the browser would be a second opinion about
 * sequence.
 */
export function markCurrent(
  revisions: readonly Revision[],
  currentRevisionId: string | null,
): readonly RevisionRow[] {
  return revisions.map((revision) => ({
    revision,
    isCurrent: currentRevisionId !== null && revision.id === currentRevisionId,
  }));
}

export type AmountView = Readonly<{ value: string; unit: "IRR" | "TOMAN" }>;

/**
 * The amount to show, taken from the server and never computed.
 *
 * `UI-REQ-003`. When the trader typed a unit, that pair is what they are shown — the digits
 * they entered beside the unit they chose. When there is no entered pair the canonical IRR
 * value is shown as IRR. In neither branch is anything multiplied, divided, parsed into a
 * number, or reformatted: `15_Agent_Implementation_Plan.md:802` makes the server
 * authoritative for the conversion, and `MONEY_TIME_CONTRACT` rule 8 keeps the value a
 * string precisely so no browser is tempted to do arithmetic on it.
 *
 * A conversion here would be a second implementation of the rule. The first time the two
 * disagreed, a goldsmith would be looking at an amount the platform does not hold.
 */
export function amountForDisplay(revision: Revision): AmountView {
  const entered: EnteredAmount | null = revision.entered_amount;
  if (entered && (entered.unit === "IRR" || entered.unit === "TOMAN")) {
    return { value: entered.value, unit: entered.unit };
  }
  return { value: revision.amount_irr, unit: "IRR" };
}
