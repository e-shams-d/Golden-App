import { t } from "@gold/localization";
import type { NavigationItem } from "@gold/ui";

/**
 * **Every item here has a page.** Three of the five did not.
 *
 * `/requests`, `/results` and `/notifications` were written in slice 9 against screens M5 to
 * M9 will build, and clicking any of them answered 404. The admin side had the same defect
 * and it was fixed when the demonstration screens landed; this side was missed, and it is
 * worse here — a goldsmith has five items to choose from and three of them are dead ends.
 *
 * The trader app is small by design and gates nothing on permissions: a trader resolves no
 * permissions at all (doc 04:405), so their access is ownership-scoped and every screen
 * they can see is their own. `visibleNavigation` therefore leaves both of these alone,
 * which is correct rather than incidental — a permission gate here would be a filter over
 * an empty set.
 *
 * `apps/trader-pwa/test/navigation.test.ts` checks the filesystem, so the next item added
 * without a page fails a test rather than a demonstration.
 */
export const traderNavigation = [
  { href: "/", label: t("trader.nav.home"), icon: "home" },
  { href: "/evidence", label: t("trader.nav.evidence"), icon: "upload" },
  { href: "/profile", label: t("trader.nav.account"), icon: "account" },
] as const satisfies readonly NavigationItem[];
