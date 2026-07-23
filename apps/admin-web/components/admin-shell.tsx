import { t } from "@gold/localization";
import { ApplicationShell } from "@gold/ui";
import type { ReactNode } from "react";

import { adminNavigation } from "../src/navigation";

export function AdminShell({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <ApplicationShell
      appName={t("admin.appName")}
      headerContext={t("admin.roleUnknown")}
      navigation={adminNavigation}
      navigationLabel="ناوبری عملیات داخلی"
      skipToContentLabel={t("common.skipToContent")}
      variant="admin"
    >
      {children}
    </ApplicationShell>
  );
}
