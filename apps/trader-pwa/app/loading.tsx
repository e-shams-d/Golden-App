import { t } from "@gold/localization";
import { StateView } from "@gold/ui";

export default function Loading() {
  return (
    <div className="p-[var(--space-page)]">
      <StateView
        description={t("state.loading.description")}
        kind="loading"
        title={t("state.loading.title")}
      />
    </div>
  );
}
