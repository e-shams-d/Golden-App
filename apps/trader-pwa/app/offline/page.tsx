import { t } from "@gold/localization";
import { StateView } from "@gold/ui";

export default function OfflinePage() {
  return (
    // `main`, not `div`: the offline screen is standalone — the service worker serves
    // it outside the shell that provides the landmark elsewhere — so without one the
    // document has no body to skip to.
    <main className="p-[var(--space-page)]">
      <StateView
        description={t("offline.description")}
        kind="error"
        title={t("offline.title")}
      />
    </main>
  );
}
