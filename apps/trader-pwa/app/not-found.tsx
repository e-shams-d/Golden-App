import { t } from "@gold/localization";
import { StateView } from "@gold/ui";
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="p-[var(--space-page)]">
      <StateView
        actions={<Link href="/">{t("common.backToHome")}</Link>}
        description={t("state.empty.description")}
        kind="empty"
        title={t("state.empty.title")}
      />
    </div>
  );
}
