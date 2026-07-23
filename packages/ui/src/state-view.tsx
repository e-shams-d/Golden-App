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
}: StateViewProps) {
  const isAlert = kind === "error" || kind === "forbidden" || kind === "conflict";

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
      <h1 className="text-2xl font-black text-[var(--ink-950)]">{title}</h1>
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
