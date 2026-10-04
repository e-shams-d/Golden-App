import { describe, expect, it } from "vitest";

import { errorMessage } from "../src/messages";

/**
 * The server refuses in English; four screens used to repeat it verbatim.
 *
 * F-2 was recorded as one stray string on `/admin-users`. It is the whole error envelope:
 * seventeen codes, every constant message in English, and `mark-sent-dialog`,
 * `bank-statements/[statementId]` and `requests/[requestId]/publication` rendering
 * `body.error.message` as-is into a Persian interface.
 *
 * **The split is deliberate and is what these tests pin.** A constant the server always
 * sends is a label, and a label in the wrong language is wrong. A message the server
 * composed for this case — "the IBAN's check digits do not match the rest of it" — is the
 * only part a reader can act on, and replacing it with a generic Persian sentence would
 * delete it.
 */

const PERSIAN_LETTERS = /[ء-يپچژکگی]/u;

describe("the message a refusal shows", () => {
  it("is Persian for a constant the server always sends", () => {
    for (const code of [
      "FORBIDDEN",
      "NOT_FOUND",
      "UNAUTHENTICATED",
      "RATE_LIMITED",
      "INTERNAL_ERROR",
    ]) {
      const shown = errorMessage(code, "Permission denied.");
      expect(shown, `${code} was left in English`).toMatch(PERSIAN_LETTERS);
      expect(shown).not.toContain("Permission denied.");
    }
  });

  it("keeps a message the server composed for this case", () => {
    // The half that makes the rule a split rather than a blanket translation. A generic
    // Persian sentence here would be more readable and less useful.
    const composed = "the IBAN's check digits do not match the rest of it";
    expect(errorMessage("BUSINESS_RULE_VIOLATION", composed)).toBe(composed);
    expect(errorMessage("VERSION_CONFLICT", "the batch is at version 3")).toBe(
      "the batch is at version 3",
    );
  });

  it("names the code when it knows neither", () => {
    // `paymentRequestStatusLabel` gives the reasoning: an invented translation for
    // something this release does not know is a claim the software cannot support. The
    // code is what somebody reads out to support.
    const shown = errorMessage("SOME_FUTURE_CODE", undefined);
    expect(shown).toMatch(PERSIAN_LETTERS);
    expect(shown).toContain("SOME_FUTURE_CODE");
  });

  it("says something readable when there is no code at all", () => {
    const shown = errorMessage(undefined, undefined);
    expect(shown).toMatch(PERSIAN_LETTERS);
    expect(shown).not.toContain("undefined");
  });

  it("prefers the constant over a server message that contradicts it", () => {
    // A 403 whose body carries some other English sentence still reads as a refusal.
    expect(errorMessage("FORBIDDEN", "something else entirely")).not.toContain("something");
  });
});
