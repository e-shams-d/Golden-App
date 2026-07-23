import { t } from "@gold/localization";
import { StateView } from "@gold/ui";

export default function OfflinePage() {
  return (
    <div className="p-[var(--space-page)]">
      <StateView
        description={t("offline.description")}
        kind="error"
        title={t("offline.title")}
      />
    </div>
  );
}
