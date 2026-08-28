"""Seed `payment_batch.cancel_approved`, granted to manager alone.

**The owner's decision of 2026-08-25**, recorded in `CONFLICT_REGISTER.md` under
DOC-CONFLICT-056 and DOC-CONFLICT-053. Until now an approved batch had no exit: §29.2 of
`06_Workflows_and_State_Machines.md:1379-1381` permits cancelling a ready-for-approval batch "with
reason" and permits replacing or cancelling an approved one before a valid final export is sent,
while `permission_catalog.yaml` contained exactly one batch cancellation permission —
`payment_batch.cancel_draft`, named for drafts. A stated rule with no permission is unreachable
under deny-by-default, so a batch a manager had approved in error could only be replaced, and
replacement carries the manager's historical approval forward onto a version they never saw.

**Authority splits by state, and that is the decision rather than a convenience.** Cancelling before
approval stays with the accountant under the existing permission: nothing has been decided yet and
the accountant is undoing their own work. Cancelling *after* approval undoes a manager's decision,
and an accountant must not be able to erase it — the same separation
`FINANCIAL_INTEGRITY_BASELINE.md` §5 makes non-configurable between finalizing and approving. So
the permission check becomes a function of the batch's **state**, not of the route alone.

**Why this migration carries a grant where `20260816_0014` deliberately carried none.** That one
seeded the two activation permissions with no `role_permissions` row, because the owner had not
chosen who holds them and borrowing a neighbouring permission would have decided it silently. Here
the owner has chosen: `manager`. Seeding the row is what makes the decision real, and leaving it
ungranted would repeat DOC-CONFLICT-056 one level further in — a permission that exists and
authorises nobody.

**Not `business_admin`.** `permission_catalog.yaml` gives it `user.read` and role management and no
payment authority at all; adding one here would widen an administrative role into the money path,
which is a decision the owner did not make. **Not `accountant`**, which is the whole point.

**Still owed by M0**, and named so it is not mistaken for complete: a `permission_catalog.yaml`
entry approved rather than added by an implementer, a `command_catalog.yaml` row for each of the
two cancellation commands — `cancel_draft` has never had one either (G-4) — and a catalogued
cancellation action for the batch aggregate, which `audit_outbox_catalog.yaml` still lacks while
naming `payment_request.cancelled` at `:25` for the request side.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0027"
down_revision: str | Sequence[str] | None = "20260826_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tuples rather than scalars, matching `20260801_0008`'s `PERMISSIONS`/`ROLE_PERMISSIONS` and
# `20260816_0014`'s `ACTIVATION_PERMISSIONS`. `test_rbac_seed_matches_catalogue.py` reads every
# seeding revision and compares the *union* against the catalogue, so a revision that expressed its
# rows differently would have to be special-cased in the test — and a comparison with a special case
# per migration is one that stops noticing the next one.
#
# The domain is read from `_0008`'s own list rather than invented: `payment_batch.cancel_draft` is
# `batch_approval_export`, and a cancellation that happens later in the same lifecycle belongs in
# the same domain.
CANCELLATION_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("payment_batch.cancel_approved", "batch_approval_export"),
)

CANCELLATION_GRANTS: tuple[tuple[str, str], ...] = (
    ("manager", "payment_batch.cancel_approved"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for code, domain in CANCELLATION_PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO permissions (code, domain) VALUES (:code, :domain) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "domain": domain},
        )
    for role, code in CANCELLATION_GRANTS:
        # Joined through the codes rather than through ids, because the ids differ per database and
        # this migration runs against every one of them.
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE r.code = :role AND p.code = :code "
                "ON CONFLICT DO NOTHING"
            ),
            {"role": role, "code": code},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for _role, code in CANCELLATION_GRANTS:
        # The grant first. Dropping the permission while a `role_permissions` row referenced it
        # would fail on the foreign key, and the other order leaves a window where a grant points
        # at nothing.
        bind.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE permission_id IN "
                "(SELECT id FROM permissions WHERE code = :code)"
            ),
            {"code": code},
        )
    for code, _domain in CANCELLATION_PERMISSIONS:
        bind.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code})
