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
  // M5 slice 8. Payment requests return, and this is the one item where the docstring's
  // action rule and its stated exception meet: the acting permissions are
  // `payment_request.review`, `.request_correction` and `.mark_eligible`, and a
  // `NavigationItem` carries one. `payment_request.read` is the gate because it is what the
  // queue route itself is guarded on, and because the three actions are all held by the same
  // role that holds the read — `accountant`. Gating on `.mark_eligible` would hide the queue
  // from nobody and misdescribe the screen, which also lists what a reviewer returned.
  {
    href: "/requests",
    label: t("admin.nav.requests"),
    permission: "payment_request.read",
    icon: "requests",
  },
  // M7 screens slice 1. The approval queue.
  //
  // `payment_batch_version.read_approval_view` rather than `payment_batch.read`, and the
  // difference is the point: the read grant goes to the roles that may see a batch, while this
  // one is what the approval-view route itself is guarded on. Gating on the weaker grant would
  // put the item in front of somebody whose every click ends in a 403.
  //
  // Not `.approve` either, for the reason the requests entry gives about its own actions:
  // `read_approval_view` goes to `accountant`, `manager` and `read_only_auditor` deliberately —
  // an auditor must see what was decided without being able to decide, and an accountant must be
  // able to check their own work. `.approve` would hide the screen from two of the three roles
  // that have a reason to open it.
  {
    href: "/batches",
    label: t("admin.nav.batches"),
    permission: "payment_batch_version.read_approval_view",
    icon: "requests",
  },
  // M8 slice 6. The bank-result queue, and the one place this docstring's action rule needs its
  // exception stated again.
  //
  // `bank_result_bundle.read` rather than an acting permission. The actions here are
  // `receipt_segment.create_crop` and `.create_external`, both held by `accountant` alone — gating
  // on either would hide the queue from `manager`, whose job includes seeing what the bank actually
  // sent, and from `read_only_auditor`, whose entire role is looking at evidence they may not
  // touch. The read is also what the list route itself is guarded on, so the item appears to
  // exactly the people whose click will not end in a 403.
  {
    href: "/bank-result-bundles",
    label: t("admin.nav.bankResults"),
    permission: "bank_result_bundle.read",
    icon: "requests",
  },
] as const satisfies readonly NavigationItem[];
