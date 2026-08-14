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
 */
export const adminNavigation = [
  { href: "/", label: t("admin.nav.dashboard") },
  { href: "/work-queues", label: t("admin.nav.queues"), permission: "manual_review.assign" },
  // `trader.approve` rather than `trader.read`: approving is what this screen is for, and
  // the three roles that hold it are the three that would use it.
  { href: "/traders", label: t("admin.nav.traders"), permission: "trader.approve" },
  {
    href: "/payment-requests",
    label: t("admin.nav.requests"),
    permission: "payment_request.review",
  },
  {
    href: "/payment-batches",
    label: t("admin.nav.batches"),
    permission: "payment_batch.create",
  },
  {
    href: "/bank-result-bundles",
    label: t("admin.nav.results"),
    permission: "bank_result_bundle.upload",
  },
  // The exception that proves the rule is a decision and not a formula. There is no
  // "act on the audit trail" permission — the trail is append-only and nobody edits it —
  // so `audit.export` is the action, and it is held by no seeded role at all. Gating on it
  // would hide the item from everyone, which is worse than showing it. `audit.read` is the
  // honest gate here, and this comment is why the pattern is broken exactly once.
  { href: "/audit", label: t("admin.nav.audit"), permission: "audit.read" },
  {
    href: "/settings",
    label: t("admin.nav.settings"),
    permission: "source_bank_account.manage",
  },
] as const satisfies readonly NavigationItem[];
