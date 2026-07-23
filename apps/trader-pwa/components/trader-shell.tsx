import { t } from "@gold/localization";
import { ApplicationShell } from "@gold/ui";
import type { ReactNode } from "react";

import { traderNavigation } from "../src/navigation";

export function TraderShell({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <ApplicationShell
      appName={t("trader.appName")}
      navigation={traderNavigation}
      navigationLabel="ناوبری اصلی طلافروش"
      skipToContentLabel={t("common.skipToContent")}
      variant="trader"
    >
      {children}
    </ApplicationShell>
  );
}
