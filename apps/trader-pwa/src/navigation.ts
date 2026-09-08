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
  // M5 slice 8. `/requests` returns, this time with a page behind it — and with an API that
  // can list them, which is what it lacked when it was removed. `/beneficiaries` arrives
  // beside it because a request cannot be opened without one, and a trader who reached the
  // draft form with no beneficiary would be sent looking for a screen that was not in the
  // navigation.
  { href: "/requests", label: t("trader.nav.requests"), icon: "requests" },
  { href: "/beneficiaries", label: t("trader.nav.beneficiaries"), icon: "beneficiaries" },
  { href: "/evidence", label: t("trader.nav.evidence"), icon: "upload" },
  { href: "/profile", label: t("trader.nav.account"), icon: "account" },
  // M11 Screens slice 1. **Carries no permission, and that is not an omission.**
  // `permission_catalog.yaml` has no notification permission at all: access is decided by
  // `notifications.recipient_actor_id`, which the server takes from the session. Naming one here
  // would mean inventing it, and gating on a neighbouring grant would hide a person's own
  // messages behind an authority that has nothing to do with them.
  // M11 Screens slice 5. Buying gold from the centre. No permission, like every item here:
  // a trader session resolves no grants at all, and the route is guarded by ownership.
  { href: "/gold-orders", label: t("gold.nav"), icon: "gold" },
  // M11 Screens slice 10. Changing your own password. No permission, like every item here.
  { href: "/password", label: t("password.nav"), icon: "key" },
  { href: "/notifications", label: t("notifications.nav"), icon: "notifications" },
] as const satisfies readonly NavigationItem[];
