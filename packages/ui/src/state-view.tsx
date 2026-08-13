import type { ReactNode } from "react";

export type StateKind =
  | "loading"
  | "error"
  | "empty"
  | "forbidden"
  | "conflict";

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
