import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { ApiError, normalizeApiError } from "../src/api-error";
import {
  APPLICATION_STATES,
  OWED_STATES,
  STATE_FOR_CODE,
  stateForError,
  stateForStatus,
  type ApplicationState,
} from "../src/application-state";

/**
 * The eighteen states, driven by envelopes the server actually produced.
 *
 * Two things make this more than a table test.
 *
 * **The floor is parsed from document 21**, not iterated from `APPLICATION_STATES`. A test
 * that derived its expectation from the thing under test would have reported green over
 * five of eighteen for as long as five was all there was — which is exactly the position
 * this repository was in before this slice.
 *
 * **The envelopes are recorded, not written.** `tests/fixtures/api_error_envelopes.json`
 * is produced by `tests/backend/test_error_envelope_fixture.py` from the real `AppError`
 * classes, and that test asserts the committed file is byte-equal to what the application
 * produces. So a status or a code changing on the server fails a Python test and changes
 * the bytes this test reads, in the same commit. Hand-typed envelopes would have proved
 * only that this file agrees with itself.
 *
 * Covers: UI-STATE-001.
 */

const REPOSITORY_ROOT = join(import.meta.dirname, "..", "..", "..");
const FIXTURE = join(REPOSITORY_ROOT, "tests", "fixtures", "api_error_envelopes.json");
const DOC_21 = join(
  REPOSITORY_ROOT,
  "Implementation Docs",
  "04_Frontend_and_Experience",
  "21_UI_Design_System_and_Screen_Specification.md",
);

type RecordedEnvelope = Readonly<{
  status: number;
  body: { error: { code: string; message: string; details: []; request_id: string } };
}>;

function recorded(): Readonly<Record<string, RecordedEnvelope>> {
  // Read rather than imported, and deliberately not wrapped in a try: a missing fixture
  // must fail this suite, not skip it. A state test that skips when its input is absent is
  // one that reports success on a machine where nothing was checked.
  return JSON.parse(readFileSync(FIXTURE, "utf8")) as Record<string, RecordedEnvelope>;
}

/**
 * Document 21 §7's bullet list, read out of the document.
 *
 * The section is "# 7. Global UI States" followed by "Every screen must implement:" and a
 * list of `- item;` lines ending in `- recent-auth required.`
 */
function documentedStates(): string[] {
  const text = readFileSync(DOC_21, "utf8");
  const section = /Every screen must implement:\n\n((?:- .*\n)+)/.exec(text);
  if (!section) throw new Error("doc 21 §7's state list could not be located");
  return section[1]!
    .split("\n")
    .filter((line) => line.startsWith("- "))
    .map((line) => line.slice(2).replace(/[;.]$/, "").trim());
}

/** The document's prose spelling for each of our names, so the comparison is by count and
 * by concept rather than by a slug the document does not use. */
const DOCUMENT_SPELLING: Readonly<Record<ApplicationState, string>> = {
  loading: "loading",
  "partial-loading": "partial loading",
  empty: "empty state",
  "permission-denied": "permission denied",
  "not-found": "not found",
  "validation-error": "validation error",
  "workflow-rejection": "workflow rejection",
  "stale-version": "stale version",
  "missing-precondition": "missing precondition",
  "idempotency-conflict": "idempotency conflict",
  "timeout-uncertain": "timeout with uncertain outcome",
  "background-processing": "background processing",
  "processing-failure": "processing failure",
  "file-quarantined": "file quarantined",
  "export-integrity-mismatch": "export integrity mismatch",
  "maintenance-read-only": "maintenance/read-only mode",
  "session-expired": "session expired",
  "recent-auth-required": "recent-auth required",
};

describe("document 21's eighteen states", () => {
  it("is still eighteen bullets in the document", () => {
    // Guard the guard. If the regular expression stopped matching, `documentedStates()`
    // would return nothing and every comparison below would be against an empty list.
    expect(documentedStates().length).toBe(18);
  });

  it("names exactly what the document names", () => {
    // Both directions. A state we invented and a state the document added are different
    // failures and both matter — the first is a name nobody agreed to, the second is a
    // screen requirement nothing implements.
    const documented = new Set(documentedStates());
    const ours = new Set(APPLICATION_STATES.map((state) => DOCUMENT_SPELLING[state]));

    expect([...documented].filter((state) => !ours.has(state))).toEqual([]);
    expect([...ours].filter((state) => !documented.has(state))).toEqual([]);
  });

  it("gives every state either an error code or a recorded owner", () => {
    // The claim that makes this table complete rather than partial: a state cannot be
    // absent from both. `OWED_STATES` is a commitment with a milestone attached, not an
    // exemption — and the next assertion stops it being used as one.
    const mapped = new Set(Object.values(STATE_FOR_CODE));
    const missing = APPLICATION_STATES.filter(
      (state) => !mapped.has(state) && !(state in OWED_STATES),
    );

    expect(missing).toEqual([]);
  });

  it("never records a state as owed while also mapping it", () => {
    const mapped = new Set(Object.values(STATE_FOR_CODE));
    const both = Object.keys(OWED_STATES).filter((state) => mapped.has(state as ApplicationState));

    expect(both, "an owed state that is already reachable is a licence nobody is using").toEqual(
      [],
    );
  });

  it("gives every owed state a milestone or a reason, not a bare marker", () => {
    for (const [state, reason] of Object.entries(OWED_STATES)) {
      expect(reason.length, `${state} is owed with no stated reason`).toBeGreaterThan(20);
    }
  });
});

describe("recorded server envelopes", () => {
  it("has envelopes to drive, so the mapping below is not tested against nothing", () => {
    expect(Object.keys(recorded()).length).toBeGreaterThanOrEqual(12);
  });

  it("maps every recorded envelope to a state, through the real error normaliser", async () => {
    // Through `normalizeApiError` and a real `Response`, not by constructing an `ApiError`
    // directly. The parsing is the part most likely to break — `isErrorEnvelope` requires
    // four fields and returns an unparsed error if any is missing, which would silently
    // send every envelope through the status fallback and make the codes untested.
    for (const [code, envelope] of Object.entries(recorded())) {
      const response = new Response(JSON.stringify(envelope.body), {
        status: envelope.status,
        headers: { "content-type": "application/json" },
      });
      const error = await normalizeApiError(response);

      expect(error.code, `${code} did not survive normalisation`).toBe(code);
      expect(stateForError(error), code).toBe(STATE_FOR_CODE[code]);
    }
  });

  it("tells a workflow rejection from a stale version, though both are 409", () => {
    // The distinction the status fallback cannot make, and the reason the codes are the
    // contract. Reloading the page fixes one and re-presents the other.
    expect(STATE_FOR_CODE.VERSION_CONFLICT).toBe("stale-version");
    expect(STATE_FOR_CODE.CONFLICT).toBe("workflow-rejection");
    expect(STATE_FOR_CODE.IDEMPOTENCY_KEY_REUSED).toBe("idempotency-conflict");
  });

  it("tells an expired session from a denial", () => {
    // Sending somebody to an administrator when their session merely lapsed is the failure
    // this separation exists to prevent.
    expect(STATE_FOR_CODE.UNAUTHENTICATED).toBe("session-expired");
    expect(STATE_FOR_CODE.FORBIDDEN).toBe("permission-denied");
  });
});

describe("what happens to a response this mapping does not know", () => {
  it("calls an unknown code uncertain rather than failed", () => {
    // Fail-safe direction. Telling somebody the operation definitely failed is a claim
    // about a response we could not read, and it is the claim that makes them retry.
    const error = new ApiError(500, { code: "SOMETHING_ADDED_LATER" });

    expect(stateForError(error)).toBe("timeout-uncertain");
  });

  it("falls back to the status when a known-shaped error carries an unmapped code", () => {
    expect(stateForError(new ApiError(404, { code: "NEW_NOT_FOUND_VARIANT" }))).toBe("not-found");
    expect(stateForError(new ApiError(428, { code: "NEW_PRECONDITION" }))).toBe(
      "missing-precondition",
    );
  });

  it("treats a network failure as uncertain, not as a failure", () => {
    // A `TypeError` from `fetch` is indistinguishable from a request that arrived and
    // whose answer was lost. The screen must not claim it knows which.
    expect(stateForError(new TypeError("Failed to fetch"))).toBe("timeout-uncertain");
  });

  it("returns no state at all for the caller's own cancellation", () => {
    // An abort is a navigation, not a condition. A screen that rendered a timeout here
    // would show an error for something the person did deliberately.
    const abort = new Error("aborted");
    abort.name = "AbortError";

    expect(stateForError(abort)).toBeUndefined();
  });

  it("has a status fallback for every status the API publishes", () => {
    for (const status of [401, 403, 404, 409, 412, 422, 428, 429, 500, 503]) {
      expect(APPLICATION_STATES).toContain(stateForStatus(status));
    }
  });
});
