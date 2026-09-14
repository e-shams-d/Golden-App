/**
 * The candidate drawer, and the one sentence it must never soften.
 *
 * M0 slice E. `workspace-screens.test.ts` proves §16.3's item is answered; this proves the answer is
 * safe. The two are different questions, and the reason to keep them apart is the failure this
 * drawer could cause: **accepting a candidate marks nothing paid**, and a screen that implied it
 * did would be the one place in this system where a person believes money moved because of a
 * button's wording. `05_API_Specification.md:1810` states the prohibition, `:1274` repeats it, and
 * `command_catalog.yaml:296` carries it as a precondition on the exact row.
 *
 * Asserted on source for `bank-configuration.test.ts`'s reason: these are claims about completeness
 * and about what is absent. The a11y sweep opens the page for real.
 *
 * Covers: UI-CANDIDATE-001.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { batchNumberInFileName } from "../src/bundles";

const APP_ROOT = join(import.meta.dirname, "..");
const BATCH_LINK = join(APP_ROOT, "components", "bundle-batch-link.tsx");
const DRAWER = join(APP_ROOT, "components", "segment-candidates.tsx");
const WORKSPACE = join(APP_ROOT, "app", "bank-result-bundles", "[bundleId]", "page.tsx");
const BUNDLES = join(APP_ROOT, "src", "bundles.ts");
const RESULTS = join(APP_ROOT, "src", "payment-results.ts");
const MESSAGES = join(APP_ROOT, "..", "..", "packages", "localization", "src", "messages.ts");

const read = (path: string): string => readFileSync(path, "utf8");

/** Comments stripped, for the assertions about what the code does *not* do. */
const code = (path: string): string =>
  read(path)
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");

/**
 * One exported function's body, bounded by the next export.
 *
 * **Written after a slice-to-end-of-file assertion failed for the wrong reason**: `proposeCandidate`
 * "contained" the word `method` because two functions below it send `method: "POST"`. An assertion
 * about what a function does not do has to end where the function does.
 */
function fn(source: string, name: string): string {
  const start = source.indexOf(`export async function ${name}`);
  expect(start, `${name} is not exported from this module`).toBeGreaterThan(-1);
  const rest = source.slice(start + 1);
  const end = rest.indexOf("\nexport ");
  return end === -1 ? rest : rest.slice(0, end);
}

describe("accepting a candidate does not look like a payment", () => {
  it("says so beside the button, not only in a docstring", () => {
    const source = code(DRAWER);

    // In the rendered output rather than in prose about the rendered output. The first version of
    // this assertion read the raw file and would have passed on the docstring alone.
    expect(source).toContain("candidate.acceptNotPaid");
    expect(source).toContain("candidate.advisory");
  });

  it("the Persian string actually denies it rather than merely omitting it", () => {
    const messages = read(MESSAGES);
    const line = messages.slice(messages.indexOf('"candidate.acceptNotPaid"'));

    // A string that said "this records the match" would satisfy a key-exists check and tell an
    // operator nothing about what has not happened. The denial is the content.
    expect(line.slice(0, 400)).toContain("ثبت نمی‌کند");
  });

  it("offers no control that could be read as confirming a payment", () => {
    const source = code(DRAWER);

    // The confirmation lives on the attempt screen and needs a bank tracking number, a result
    // timestamp and a person. None of those can be collected here, so none of them appear.
    expect(source).not.toContain("confirmPaid");
    expect(source).not.toContain("bank_result_at");
    expect(source).not.toContain("confirm-paid");
  });
});

describe("the candidate data module", () => {
  it("sends no score and no method when a person proposes", () => {
    const propose = fn(code(BUNDLES), "proposeCandidate");

    // **Asserted on the body rather than on the function**, because every request in this module
    // carries `method: "POST"` — the HTTP verb, which is not what `ProposeRequest.method` means.
    // The first version of this test read the whole function and failed on that collision.
    const body = propose.slice(propose.indexOf("body: {"), propose.indexOf("idempotencyKey"));

    // A score from a screen would be a human guess wearing the shape of something computed, which
    // is the reason `ProposeRequest` refuses to default one to 1.0. `method` is the third member of
    // the unique that lets an engine later suggest the same pair a person already did.
    expect(body).toContain("payment_attempt_id");
    expect(body).not.toContain("score");
    expect(body).not.toContain("method");
  });

  it("carries an idempotency key on all three commands", () => {
    const source = code(BUNDLES);
    for (const name of ["proposeCandidate", "acceptCandidate", "rejectCandidate"]) {
      expect(fn(source, name), `${name} sends no idempotency key`).toContain("idempotencyKey");
    }
  });

  it("requires a reason for a rejection rather than defaulting one", () => {
    const reject = fn(code(BUNDLES), "rejectCandidate");

    // `reason: string`, not `string | undefined`: the server requires one for every rejection, and
    // a default here would send a sentence nobody wrote.
    expect(reject).toMatch(/reason:\s*string[,)]/);
  });

  it("sends only allowlisted filters on the attempt search", () => {
    const search = fn(code(RESULTS), "searchAttempts");

    // The server refuses an unknown filter rather than ignoring it. Sending one the allowlist does
    // not hold would turn a search into a 400 the operator cannot act on.
    for (const field of ["amount_irr", "bank_tracking_number", "status", "payment_request_id"]) {
      expect(search).toContain(field);
    }
    expect(search).not.toContain("beneficiary");
    expect(search).not.toContain("iban");
  });
});

describe("the drawer refuses what the server would refuse", () => {
  it("will not reject without a reason", () => {
    const source = code(DRAWER);
    const button = source.slice(source.indexOf('data-testid="candidate-reject"'));

    expect(button).toContain('(reasons[candidate.id] ?? "").trim() === ""');
  });

  it("will not search with both fields empty", () => {
    const source = code(DRAWER);
    const button = source.slice(source.indexOf('data-testid="candidate-search"'));

    // An unfiltered search returns every attempt in the centre, which is not a search.
    expect(button).toContain('amount.trim() === "" && tracking.trim() === ""');
  });

  it("refuses an amount that cannot survive the trip through a number", () => {
    const source = code(DRAWER);

    // `MONEY_TIME_CONTRACT.md` rule 9 forbids JavaScript `Number` for an IRR figure, and the
    // contract's query parameter is an integer. Rounding silently would search for a different
    // amount than the one on screen and find the wrong attempt — a plausible wrong one.
    expect(source).toContain("Number.isSafeInteger");
    expect(source).toContain("candidate.amountTooLarge");
  });

  it("offers a decision only on a candidate still open", () => {
    const source = code(DRAWER);

    // Accepting an already-rejected candidate is refused by the command; the screen not offering it
    // is the difference between learning that before the click and after.
    expect(source).toContain("candidate.status === OPEN");
  });
});

describe("the drawer reads what the server actually returns", () => {
  it("distinguishes a missing score from a low one", () => {
    const source = code(DRAWER);

    // Null means nobody computed a score, which is what every manual proposal looks like. Rendering
    // it as 0 would say something was computed and found unlikely.
    expect(source).toContain("candidate.score === null");
    expect(source).toContain("candidate.noScore");
  });

  it("seeds the search from the segment rather than from an empty box", () => {
    const source = code(DRAWER);

    expect(source).toContain("segment.extracted_amount_irr");
    expect(source).toContain("segment.extracted_tracking_number");
  });

  it("says when the platform read nothing off the receipt", () => {
    const source = code(DRAWER);

    // §8.4 leaves an unparseable field null rather than guessing. "We read nothing" and "the
    // receipt was blank" are different facts, and only the first is true here.
    expect(source).toContain("candidate.nothingExtracted");
  });
});

describe("the file name suggests a batch and never decides one", () => {
  it("finds a batch number in a name the bank did not touch", () => {
    expect(batchNumberInFileName("PB-20260913-000001-results.xlsx")).toBe("PB-20260913-000001");
    expect(batchNumberInFileName("نتیجه PB-20260913-000042.xlsx")).toBe("PB-20260913-000042");
  });

  it("finds nothing in a name that only looks like one", () => {
    // **The pattern is strict on purpose.** A looser one would match a date in a file name and
    // pre-select a batch at random — worse than matching nothing, because the operator would be
    // confirming a suggestion instead of making a choice.
    expect(batchNumberInFileName("20260913.xlsx")).toBeNull();
    expect(batchNumberInFileName("PB-2026-1.xlsx")).toBeNull();
    expect(batchNumberInFileName("PB-20260913-0001.xlsx")).toBeNull();
    expect(batchNumberInFileName("results.xlsx")).toBeNull();
    // A longer digit run is a *different* number, not this one with something after it. Matching
    // the first six would pre-select a batch nobody named.
    expect(batchNumberInFileName("PB-20260913-0000012.xlsx")).toBeNull();
    // And a number glued to other text is not a number this platform issued.
    expect(batchNumberInFileName("XPB-20260913-000001.xlsx")).toBeNull();
  });

  it("survives the three ways a name gets changed in transit", () => {
    // A download adding `(1)`, a mail client prefixing, a bank appending. None of these should lose
    // a number that is still in the name — and none of them is a reason to trust the name.
    expect(batchNumberInFileName("PB-20260913-000001 (1).xlsx")).toBe("PB-20260913-000001");
    expect(batchNumberInFileName("FW_ PB-20260913-000001.xlsx")).toBe("PB-20260913-000001");
    expect(batchNumberInFileName("PB-20260913-000001_bank_final_v2.xlsx")).toBe(
      "PB-20260913-000001",
    );
  });

  it("says the suggestion is a guess, beside the suggestion", () => {
    const source = code(BATCH_LINK);

    // The whole reason a name may be shown at all. Without this an operator reads a pre-selected
    // batch as something the platform knows rather than something it noticed.
    expect(source).toContain("batchLink.suggestionIsAGuess");
    expect(source).toContain("batchLink.suggestion");
  });

  it("records a person's choice as a person's choice", () => {
    const source = code(BATCH_LINK);

    // `manual_selection` is one of the three values the schema's CHECK allows, and it is what makes
    // a human decision distinguishable from an import's guess a month later.
    expect(source).toContain('"manual_selection"');
  });

  it("says the link is not proof of payment, before showing a batch number", () => {
    const source = code(BATCH_LINK);

    // `05_API_Specification.md:1688` calls the association "operational context only". A batch
    // number beside a bundle reads as a claim unless a sentence contradicts it.
    expect(source).toContain("batchLink.notProof");
    expect(source.indexOf("batchLink.notProof")).toBeLessThan(source.indexOf("batch-link-list"));
  });

  it("keeps superseded links visible rather than replacing the record", () => {
    const source = code(BATCH_LINK);

    // `replaced_at` is set and the row stays. A screen that showed only the active link would make
    // "who attached this to that batch, and when did it change" unanswerable from the screen that
    // changed it.
    expect(source).toContain("link.replaced_at !== null");
    expect(source).toContain("batchLink.previous");
  });
});

describe("the workspace keeps the drawer and the crop surface independent", () => {
  it("does not fail the page when the segment list is refused", () => {
    const source = code(WORKSPACE);

    // Cropping is what this workspace is for. A role holding `bank_result_bundle.read` and not the
    // candidate grant must still be able to crop, so the segment read's failure is caught.
    expect(source).toContain("setSegments([])");
  });

  it("remounts the drawer when another segment is chosen", () => {
    const source = code(WORKSPACE);

    // Without the key, one segment's candidates and search results stay on screen while another is
    // selected — and a decision would be made about the wrong receipt.
    expect(source).toContain("key={selectedSegment.id}");
  });

  it("derives the selected segment rather than defaulting it in an effect", () => {
    const source = code(WORKSPACE);

    // `react-hooks/set-state-in-effect` forbids the effect, and the derivation cannot go stale when
    // a reload returns a different set of segments.
    expect(source).toContain("segments.find((segment) => segment.id === selectedSegmentId)");
    expect(source).not.toMatch(/useEffect\([^)]*setSelectedSegmentId/);
  });
});
