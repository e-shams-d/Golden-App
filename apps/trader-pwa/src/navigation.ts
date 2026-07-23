import { t } from "@gold/localization";
import type { NavigationItem } from "@gold/ui";

export const traderNavigation = [
  { href: "/", label: t("trader.nav.home") },
  { href: "/requests", label: t("trader.nav.requests") },
  { href: "/results", label: t("trader.nav.results") },
  { href: "/notifications", label: t("trader.nav.notifications") },
  { href: "/profile", label: t("trader.nav.account") },
] as const satisfies readonly NavigationItem[];
