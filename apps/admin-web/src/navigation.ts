import { t } from "@gold/localization";
import type { NavigationItem } from "@gold/ui";

/**
 * The centre's navigation, and which permission each item is gated on.
 *
 * **Gated on the permission that lets you *act* there, not the one that lets you read it.**
 * That is a product decision, recorded by the owner during slice 10D, and the reason it had
 * to be asked rather than inferred is in the seeded catalogue: `accountant` — the only
 * unprivileged internal role that exists — holds `trader.read`, `audit.read`,
 * `payment_request.read`, `bank_result_bundle.read` and `bank_profile.read`. There is a
 * read permission behind every item below. Gating on reads would hide nothing from
 * anybody, and the test asserting that navigation reflects permissions would have had to be
 * written against a permission nobody is granted.
 *
 * **None of this is a control.** `12_Security_RBAC_Audit.md:625-626` makes the server
 * authoritative. A hidden item is not a denial: typing the URL still reaches the route, and
 * the route still refuses. `UI-NAV-001`'s second half is what proves that, and it is the
 * half that must survive if the first ever becomes expensive.
 *
 * The dashboard carries no permission because it is what an authenticated person lands on;
 * an item everybody reaches needs no gate, and inventing one for it would be a permission
 * that exists only to satisfy a type.
 *
 * **Every item here has a page**, which was not true until this slice. Six of the eight
 * pointed at routes that do not exist, so clicking them answered 404 — and slice 10D made
 * that worse rather than better, because a personalised menu reads as a menu whose items
 * work. A `business_admin` saw four items of which two were dead.
 *
 * `test_every_navigation_target_has_a_page` is what keeps it true. Work queues, payment
 * requests, batches, bank results, audit and settings return with the milestones that build
 * their screens (M4–M6); an item comes back when its page does, not before. The audit item
 * carries a decision worth keeping for when it returns: there is no "act on the audit
 * trail" permission, because the trail is append-only and nobody edits it, and
 * `audit.export` — the nearest action — is held by **no** seeded role, so gating on it
 * would hide the item from everyone. `audit.read` is the honest gate there, and it is the
 * one place the action rule is deliberately broken.
 */
export const adminNavigation = [
  { href: "/", label: t("admin.nav.dashboard"), icon: "dashboard" },
  // `trader.approve` rather than `trader.read`: approving is what this screen is for, and
  // the three roles that hold it are the three that would use it.
  { href: "/traders", label: t("admin.nav.traders"), permission: "trader.approve", icon: "traders" },
  // Staff administration. `user.read` is the action here in the sense that matters — it is
  // the permission the list route is guarded on, and it is held by `business_admin` alone,
  // so it discriminates without needing a stronger one.
  { href: "/admin-users", label: t("admin.nav.staff"), permission: "user.read", icon: "staff" },
  // Roles are read-only for now; `role.read` is the guard the route carries. Gating on
  // `role.manage` would hide the screen from `manager`, who holds the read and has a
  // legitimate reason to see why a colleague's menu differs from theirs.
  { href: "/roles", label: t("admin.nav.roles"), permission: "role.read", icon: "roles" },
] as const satisfies readonly NavigationItem[];
