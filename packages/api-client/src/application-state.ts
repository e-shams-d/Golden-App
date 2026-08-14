/**
 * Turning a server response into one of document 21's eighteen application states.
 *
 * `21_UI_Design_System_and_Screen_Specification.md` §7 says "every screen must implement"
 * and then lists eighteen states. **Four of them existed.** `packages/ui`'s `StateKind`
 * carried loading, empty, forbidden and conflict; nothing anywhere turned a status code or
 * an error code into any of them, so a real server response could not drive a state at
 * all. Six months of screens would each have invented their own reading of a 409.
 *
 * **The plan said twelve were missing and the real number is eleven.** Its list includes
 * "empty state", which `StateKind` has had since slice 9. Counting from the document
 * rather than from the plan is the only way that error surfaces — which is why the floor
 * in `test/application-state.test.ts` is parsed out of the document's own bullets rather
 * than written here.
 *
 * ## Why this lives beside `ApiError` and not in `packages/ui`
 *
 * `packages/ui` has no dependency on the API client, deliberately: it is presentation, and
 * a component package that knew about HTTP would be one that could not be rendered without
 * one. So the split is by question rather than by convenience —
 *
 *   *what happened* is an error-shaped question and is answered here;
 *   *what it should look like* is a presentation question and is answered by
 *   `packages/ui`'s `kindForApplicationState`.
 *
 * Neither imports the other. `ApplicationState` is a union of plain strings, so `ui` keys
 * its table on the same eighteen names without needing this module, and
 * `apps/admin-web/test/application-state.test.ts` — which depends on both — is what
 * asserts the two tables still agree.
 *
 * ## What is deliberately not decided here
 *
 * Seven of the eighteen describe things this platform does not have before M6: files,
 * exports, background jobs, maintenance mode. They are in `OWED_STATES` with the milestone
 * that owns each, rather than mapped to a code that would never arrive. A state mapped to
 * an error the server cannot emit reads as covered and renders never.
 */

import { ApiError } from "./api-error";

/**
 * Document 21 §7's eighteen, in the document's order.
 *
 * The order is not decoration: `test/application-state.test.ts` parses the same list out
 * of the document and compares, so a state added to §7 fails here rather than being
 * quietly absent from every screen that claims to implement "every state".
 */
export const APPLICATION_STATES = [
  "loading",
  "partial-loading",
  "empty",
  "permission-denied",
  "not-found",
  "validation-error",
  "workflow-rejection",
  "stale-version",
  "missing-precondition",
  "idempotency-conflict",
  "timeout-uncertain",
  "background-processing",
  "processing-failure",
  "file-quarantined",
  "export-integrity-mismatch",
  "maintenance-read-only",
  "session-expired",
  "recent-auth-required",
] as const;

export type ApplicationState = (typeof APPLICATION_STATES)[number];

/**
 * The approved error catalogue's codes, each to the state it means.
 *
 * Keyed on `docs/governance/api_error_catalog.yaml` rather than on the nine codes the
 * backend happens to raise today. The catalogue is the contract; mapping only what is
 * currently thrown would leave a screen with no state the first time a route starts
 * returning a code that was always allowed. `test_error_catalog_is_fully_mapped.py`
 * compares this table against that file.
 *
 * Two of these are worth reading twice.
 *
 * `UNAUTHENTICATED` is `session-expired` rather than `permission-denied`. The distinction
 * is the whole point of having both: denied means "you may not", expired means "sign in
 * again", and telling somebody they lack permission when their session simply lapsed sends
 * them to an administrator instead of to the login form.
 *
 * `CONFLICT` is `workflow-rejection` and `VERSION_CONFLICT` is `stale-version`. Both are
 * 409s. Collapsing them onto one state would tell a person to reload the page when what
 * actually happened is that the business refused their request — and reloading would
 * present the same refusal again.
 */
export const STATE_FOR_CODE: Readonly<Record<string, ApplicationState>> = {
  UNAUTHENTICATED: "session-expired",
  FORBIDDEN: "permission-denied",
  RECENT_AUTH_REQUIRED: "recent-auth-required",
  NOT_FOUND: "not-found",
  VALIDATION_ERROR: "validation-error",
  BAD_REQUEST: "validation-error",
  IBAN_INVALID: "validation-error",
  UNSUPPORTED_FILE_TYPE: "validation-error",
  FILE_TOO_LARGE: "validation-error",
  AMOUNT_UNIT_MISMATCH: "validation-error",
  BUSINESS_RULE_VIOLATION: "workflow-rejection",
  INVALID_STATE_TRANSITION: "workflow-rejection",
  CONFLICT: "workflow-rejection",
  ACTIVE_BATCH_MEMBERSHIP_EXISTS: "workflow-rejection",
  ACTIVE_PRIMARY_EVIDENCE_EXISTS: "workflow-rejection",
  APPROVAL_INVALIDATED: "workflow-rejection",
  RECONCILIATION_REQUIRED: "workflow-rejection",
  VERSION_CONFLICT: "stale-version",
  PRECONDITION_REQUIRED: "missing-precondition",
  IDEMPOTENCY_KEY_REUSED: "idempotency-conflict",
  BACKGROUND_PROCESSING_UNAVAILABLE: "background-processing",
  EXPORT_INTEGRITY_MISMATCH: "export-integrity-mismatch",
  // Both mean "the server could not answer and the outcome is unknown". A retry is safe
  // only where the caller sent an idempotency key, which is why the state says uncertain
  // rather than failed — a screen that said "it failed" would invite a second payment.
  DEPENDENCY_UNAVAILABLE: "timeout-uncertain",
  INTERNAL_ERROR: "timeout-uncertain",
  RATE_LIMITED: "timeout-uncertain",
};

/**
 * States no error code reaches, with the milestone that owns each.
 *
 * A commitment, not an exemption. `test/application-state.test.ts` fails if an entry here
 * is also in `STATE_FOR_CODE`, and fails if the two together do not cover all eighteen —
 * so a state cannot be quietly absent from both.
 */
export const OWED_STATES: Readonly<Record<string, string>> = {
  // Not error-driven at all: these three are what a screen shows while it is working,
  // when it has some of the data, and when a successful response contains nothing.
  // `stateForError` is the wrong door for them, and `packages/ui` renders all three today.
  loading: "not error-driven; a screen sets it while a request is in flight",
  "partial-loading": "not error-driven; set when a screen has some sections and not others",
  empty: "not error-driven; a 200 whose collection is empty",
  // Real gaps, each waiting on a subsystem that does not exist yet.
  "processing-failure": "M6 — no background job reports a per-item failure before then",
  "file-quarantined": "M6 — file upload and the scanner arrive together (ADR-SEC-006)",
  "maintenance-read-only": "M7 — no read-only mode exists; nothing can emit it",
};

/**
 * What state a caught throwable means.
 *
 * **An unrecognised code is `timeout-uncertain`, not a generic error, and that is the
 * fail-safe direction.** A code this table does not know is one whose meaning nobody has
 * decided; telling the person the operation definitely failed would be a claim about a
 * response we could not read. "The outcome is uncertain — check before retrying" is true
 * whatever the code turned out to mean.
 *
 * An `AbortError` is the caller's own cancellation and is **not** an application state.
 * A screen that navigated away should render nothing, not a timeout, so this returns
 * `undefined` and the caller keeps its current view — which is what the abort was for.
 */
export function stateForError(error: unknown): ApplicationState | undefined {
  if (isAbort(error)) return undefined;

  if (error instanceof ApiError) {
    const byCode = STATE_FOR_CODE[error.code];
    if (byCode) return byCode;
    return stateForStatus(error.status);
  }

  // A `TypeError` from `fetch` is the network refusing, which is indistinguishable from a
  // request that arrived and whose answer was lost. Uncertain, for the reason above.
  return "timeout-uncertain";
}

/**
 * The status-code fallback, for a response whose code this table does not carry.
 *
 * Deliberately coarse. It exists so an unmapped code still lands somewhere truthful, not
 * so that statuses become a second mapping people maintain — the codes are the contract
 * and `STATE_FOR_CODE` is where a new one belongs.
 */
export function stateForStatus(status: number): ApplicationState {
  if (status === 401) return "session-expired";
  if (status === 403) return "permission-denied";
  if (status === 404) return "not-found";
  if (status === 412) return "stale-version";
  if (status === 422) return "validation-error";
  if (status === 428) return "missing-precondition";
  if (status === 409) return "workflow-rejection";
  if (status >= 400 && status < 500) return "validation-error";
  return "timeout-uncertain";
}

function isAbort(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name: unknown }).name === "AbortError"
  );
}
