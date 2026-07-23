"use client";

import { t } from "@gold/localization";
import { StateView } from "@gold/ui";

export default function ErrorBoundary({
  error,
  reset,
}: Readonly<{ error: Error & { digest?: string }; reset: () => void }>) {
  return (
    <div className="p-[var(--space-page)]">
      <StateView
        actions={
          <button
            className="rounded-lg bg-[var(--ink-950)] px-4 py-3 font-bold text-white"
            onClick={reset}
            type="button"
          >
            {t("common.retry")}
          </button>
        }
        description={t("state.error.description")}
        kind="error"
        requestId={error.digest}
        title={t("state.error.title")}
      />
    </div>
  );
}
