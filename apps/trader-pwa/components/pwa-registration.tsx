"use client";

import { t } from "@gold/localization";
import { useEffect, useState } from "react";

export function PwaRegistration() {
  const [waitingWorker, setWaitingWorker] = useState<ServiceWorker | null>(null);

  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) {
      return undefined;
    }

    let active = true;

    const detectWaitingWorker = (candidate: ServiceWorkerRegistration) => {
      if (active && candidate.waiting) setWaitingWorker(candidate.waiting);
    };

    void navigator.serviceWorker.register("/sw.js", { scope: "/" }).then((candidate) => {
      detectWaitingWorker(candidate);
      candidate.addEventListener("updatefound", () => {
        candidate.installing?.addEventListener("statechange", () => {
          if (candidate.installing?.state === "installed" && navigator.serviceWorker.controller) {
            detectWaitingWorker(candidate);
          }
        });
      });
    }).catch(() => undefined);

    return () => {
      active = false;
    };
  }, []);

  if (!waitingWorker) return null;

  const applyUpdate = () => {
    navigator.serviceWorker.addEventListener("controllerchange", () => window.location.reload(), {
      once: true,
    });
    waitingWorker.postMessage({ type: "SKIP_WAITING" });
  };

  return (
    <aside
      aria-live="polite"
      className="fixed inset-x-4 bottom-20 z-50 mx-auto flex max-w-xl flex-col gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-[var(--shadow-raised)] sm:flex-row sm:items-center sm:justify-between"
    >
      <p className="leading-7">{t("pwa.updateAvailable")}</p>
      <button
        className="min-h-11 shrink-0 rounded-lg bg-[var(--ink-950)] px-4 font-bold text-white"
        onClick={applyUpdate}
        type="button"
      >
        {t("pwa.applyUpdate")}
      </button>
    </aside>
  );
}
