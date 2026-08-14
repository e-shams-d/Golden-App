import type { ReactNode } from "react";

/**
 * How a state looks, which is a smaller question than what it means.
 *
 * Eight kinds for document 21's eighteen states, and the eight-to-eighteen gap is
 * deliberate rather than unfinished: `stale-version` and a workflow rejection are
 * different *facts* and are told apart by `@gold/api-client`'s `ApplicationState`, but on
 * screen they are both "we could not apply this, here is what to do". Giving each of the
 * eighteen its own visual treatment would be eighteen designs nobody could hold in mind,
 * and the distinctions that matter are carried by the title and description a screen
 * passes in.
 *
 * The three added in slice 10C — `precondition`, `idempotency` and `timeout` — are the
 * ones the plan's own six named and no component had. `timeout` is the important one: it
 * is visually distinct from `error` on purpose, because a person who is told an operation
 * failed will retry it and a person told the outcome is unknown will check first.
 */
export type StateKind =
  | "loading"
  | "error"
  | "empty"
  | "forbidden"
  | "conflict"
  | "precondition"
  | "idempotency"
  | "timeout";

/**
 * The runtime list, so a caller can check a value rather than only a type.
 *
 * A `type` alone disappears at build time, and the parity test between this package and
 * `@gold/api-client` needs something it can iterate.
 */
export const STATE_KINDS = [
  "loading",
  "error",
  "empty",
  "forbidden",
  "conflict",
  "precondition",
  "idempotency",
  "timeout",
] as const satisfies readonly StateKind[];

/**
 * Document 21 §7's eighteen states, each to the kind that renders it.
 *
 * Keyed by plain strings and **not** by importing `ApplicationState`: this package has no
 * dependency on the API client, deliberately, because a presentation package that needed
 * HTTP could not be rendered without it. The two tables are held in agreement by
 * `apps/admin-web/test/application-state.test.ts`, which depends on both — a compile-time
 * link would have required exactly the dependency this avoids.
 */
export const KIND_FOR_APPLICATION_STATE: Readonly<Record<string, StateKind>> = {
  loading: "loading",
  // The same spinner, and a screen showing partial data passes a description saying which
  // part is still arriving. Doc 21 §7.1 forbids a misleading zero total while loading,
  // which is a rule about content rather than about the chrome around it.
  "partial-loading": "loading",
  empty: "empty",
  "permission-denied": "forbidden",
  "not-found": "empty",
  "validation-error": "error",
  "workflow-rejection": "error",
  "stale-version": "conflict",
  "missing-precondition": "precondition",
  "idempotency-conflict": "idempotency",
  "timeout-uncertain": "timeout",
  "background-processing": "loading",
  "processing-failure": "error",
  "file-quarantined": "error",
  "export-integrity-mismatch": "error",
  "maintenance-read-only": "forbidden",
  // Not `forbidden`. Somebody whose session lapsed needs the login form; telling them
  // their access is restricted sends them to an administrator instead.
  "session-expired": "error",
  "recent-auth-required": "precondition",
};

/** The kind that renders a state, or `error` for a name this table does not carry. */
export function kindForApplicationState(state: string): StateKind {
  return KIND_FOR_APPLICATION_STATE[state] ?? "error";
}

export type StateViewProps = Readonly<{
  kind: StateKind;
  title: string;
  description: string;
  requestId?: string | undefined;
  actions?: ReactNode;
  /**
   * Which heading level the title becomes. Defaults to `1`, which is correct when this
   * view *is* the page, and must be lowered when it sits inside a screen that already has
   * a title — two level-one headings is an accessibility defect, not a style preference.
   */
  headingLevel?: 1 | 2 | 3;
}>;

const stateLabels: Record<StateKind, string> = {
  loading: "در حال پردازش",
  error: "خطا",
  empty: "بدون داده",
  forbidden: "دسترسی محدود",
  conflict: "تعارض نسخه",
  precondition: "پیش‌نیاز انجام نشده",
  idempotency: "درخواست تکراری",
  // "The result is not clear" rather than "failed". The wording is the control: a person
  // told an operation failed retries it, and this state exists precisely for the case
  // where a retry could apply the same change twice.
  timeout: "نتیجه نامشخص",
};

export function StateView({
  kind,
  title,
  description,
  requestId,
  actions,
  headingLevel = 1,
}: StateViewProps) {
  const isAlert = kind === "error" || kind === "forbidden" || kind === "conflict";
  // A document has one `h1`. This component hard-coded one, which was right while it was
  // the whole content of a page — the `/states/[kind]` screens — and became a real defect
  // the moment a screen with its own title embedded it: the accessibility sweep reported
  // two level-one headings on the trader-approval page the first time it ran there.
  //
  // Defaulting to 1 keeps every existing call site rendering exactly what it rendered
  // before, so this is additive rather than a behaviour change somebody has to notice.
  const Heading = `h${headingLevel}` as "h1" | "h2" | "h3";

  return (
    <section
      aria-busy={kind === "loading"}
      aria-live={kind === "loading" ? "polite" : undefined}
      className="mx-auto flex min-h-72 w-full max-w-2xl flex-col items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-8 text-center shadow-[var(--shadow-raised)]"
      role={isAlert ? "alert" : "status"}
    >
      <span className="mb-4 rounded-full border border-current px-3 py-1 text-sm font-bold">
        {stateLabels[kind]}
      </span>
      <Heading className="text-2xl font-black text-[var(--ink-950)]">{title}</Heading>
      <p className="mt-3 max-w-prose leading-8 text-[var(--ink-600)]">{description}</p>
      {requestId ? (
        <p className="mt-4 text-sm text-[var(--ink-600)]">
          شناسه پیگیری: <span dir="ltr">{requestId}</span>
        </p>
      ) : null}
      {actions ? <div className="mt-6 flex flex-wrap justify-center gap-3">{actions}</div> : null}
    </section>
  );
}
