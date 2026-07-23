import { t } from "@gold/localization";
import type { NavigationItem } from "@gold/ui";

export const adminNavigation = [
  { href: "/", label: t("admin.nav.dashboard") },
  { href: "/work-queues", label: t("admin.nav.queues") },
  { href: "/traders", label: t("admin.nav.traders") },
  { href: "/payment-requests", label: t("admin.nav.requests") },
  { href: "/payment-batches", label: t("admin.nav.batches") },
  { href: "/bank-result-bundles", label: t("admin.nav.results") },
  { href: "/audit", label: t("admin.nav.audit") },
  { href: "/settings", label: t("admin.nav.settings") },
] as const satisfies readonly NavigationItem[];
