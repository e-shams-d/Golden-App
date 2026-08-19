import { describe, expect, it } from "vitest";

import { amountPayload } from "../src/payment-requests";
import type { PaymentRequest, Revision } from "../src/payment-requests";
import { amountForDisplay, correctionNotice, markCurrent } from "../src/request-view";

/**
 * What the request screens decide, tested where the deciding is.
 *
 * There is no jsdom in this repository and no testing-library: the frontend suites are vitest
 * over source and filesystem, and real rendering is proved by Playwright in `tests/a11y` and
 * `tests/demo`. Asserting "the screen shows the note" by grepping JSX would be a test of a
 * string, so the screens' judgements live in `src/request-view.ts` and are tested here as
 * functions. That the note *reaches* the browser at all is proved server-side, in
 * `tests/integration/test_payment_request_review.py`.
 *
 * Covers: UI-REQ-001, UI-REQ-002, UI-REQ-003.
 */

function request(overrides: Partial<PaymentRequest> = {}): PaymentRequest {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    trader_id: "22222222-2222-2222-2222-222222222222",
    beneficiary_id: "33333333-3333-3333-3333-333333333333",
    request_number: "GP-202608-0001",
    status: "needs_trader_correction",
    current_revision_id: "44444444-4444-4444-4444-444444444444",
    review_note: null,
    reviewed_at: null,
    record_version: 3,
    ...overrides,
  };
}

function revision(overrides: Partial<Revision> = {}): Revision {
  return {
    id: "44444444-4444-4444-4444-444444444444",
    revision_number: 1,
    beneficiary_name_snapshot: "علی یک",
    beneficiary_iban_snapshot: "IR060120000000000000000001",
    amount_irr: "5000",
    entered_amount: { value: "500", unit: "TOMAN" },
    description: null,
    content_hash: "a".repeat(64),
    ...overrides,
  };
}

describe("the reviewer's note (UI-REQ-001)", () => {
  it("is returned when the centre sent one", () => {
    const note = "شبای ذی‌نفع را اصلاح کنید.";

    expect(correctionNotice(request({ review_note: note }))).toBe(note);
  });

  it("is null when there is none, so the screen renders no empty panel", () => {
    expect(correctionNotice(request({ review_note: null }))).toBeNull();
  });

  it("treats whitespace as nothing", () => {
    // A note of spaces would render as a highlighted empty box, which reads as "the centre
    // said something and this screen lost it".
    expect(correctionNotice(request({ review_note: "   " }))).toBeNull();
  });

  it("does not hide the note on a status the screen did not expect", () => {
    // Deliberately not gated on `needs_trader_correction`. A screen that filtered by status
    // would be deciding which of the centre's messages its owner may read.
    expect(
      correctionNotice(request({ status: "eligible_for_batching", review_note: "بررسی شد." })),
    ).toBe("بررسی شد.");
  });
});

describe("the revision history (UI-REQ-002)", () => {
  const first = revision({ id: "aaaaaaaa-0000-0000-0000-000000000001", revision_number: 1 });
  const second = revision({ id: "aaaaaaaa-0000-0000-0000-000000000002", revision_number: 2 });
  const third = revision({ id: "aaaaaaaa-0000-0000-0000-000000000003", revision_number: 3 });

  it("keeps every revision, in the order the server gave", () => {
    const rows = markCurrent([first, second, third], third.id);

    // Ids rather than a length: a length passes on a list that dropped one and duplicated
    // another, which is exactly the failure a history must not have.
    expect(rows.map((row) => row.revision.id)).toEqual([first.id, second.id, third.id]);
  });

  it("marks exactly the current one", () => {
    const rows = markCurrent([first, second, third], second.id);

    expect(rows.filter((row) => row.isCurrent).map((row) => row.revision.id)).toEqual([
      second.id,
    ]);
  });

  it("marks nothing when the request has no current revision", () => {
    expect(markCurrent([first, second], null).some((row) => row.isCurrent)).toBe(false);
  });

  it("marks nothing when the current id is not in the history", () => {
    // Would mean the two reads disagreed. Marking the last row anyway would invent a fact.
    expect(markCurrent([first, second], third.id).some((row) => row.isCurrent)).toBe(false);
  });
});

describe("the amount (UI-REQ-003)", () => {
  it("shows what was typed, in the unit that was chosen", () => {
    const view = amountForDisplay(revision({ entered_amount: { value: "500", unit: "TOMAN" } }));

    // 500 TOMAN, not 5000 IRR. The canonical value is on the same revision and is
    // deliberately not what a trader is shown when they typed something else.
    expect(view).toEqual({ value: "500", unit: "TOMAN" });
  });

  it("falls back to the canonical value as IRR when nothing was typed", () => {
    const view = amountForDisplay(revision({ entered_amount: null, amount_irr: "5000" }));

    expect(view).toEqual({ value: "5000", unit: "IRR" });
  });

  it("does not convert, in either direction", () => {
    const asToman = amountForDisplay(
      revision({ entered_amount: { value: "500", unit: "TOMAN" }, amount_irr: "5000" }),
    );
    const asRials = amountForDisplay(
      revision({ entered_amount: { value: "5000", unit: "IRR" }, amount_irr: "5000" }),
    );

    // The digits are the server's, character for character. A ten-times factor anywhere in
    // the display path changes one of these two.
    expect(asToman.value).toBe("500");
    expect(asRials.value).toBe("5000");
  });

  it("keeps a value too large for a JavaScript number exact", () => {
    // Beyond `Number.MAX_SAFE_INTEGER`: parsing this into a float and back loses digits, and
    // an IRR settlement reaches this size. The string is carried through untouched.
    const huge = "9007199254740993000";
    const view = amountForDisplay(revision({ entered_amount: { value: huge, unit: "IRR" } }));

    expect(view.value).toBe(huge);
  });

  it("sends the typed digits and the chosen unit, and nothing else", () => {
    // The wire shape. A browser-side conversion would have to change this function or add a
    // field beside it, and both fail here.
    expect(amountPayload("500", "TOMAN")).toEqual({ value: "500", unit: "TOMAN" });
    expect(Object.keys(amountPayload("500", "TOMAN")).sort()).toEqual(["unit", "value"]);
  });
});
