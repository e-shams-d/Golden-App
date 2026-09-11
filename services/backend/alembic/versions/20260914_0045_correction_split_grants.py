"""Grant the publication-correction split and bank-version activation.

**The owner's decisions of 2026-09-08**, resolving three permissions that had been seeded and
deliberately granted to nobody.

## The correction split, which POL-002 deferred to ADR-SEC-009

`payment_publication.correct` and `payment_attempt.correct_result` were seeded by `20260801_0008`
with `default_roles: []` and an `assignment` note saying the preparer and approver halves must be
split once the ADR existed. It did not exist, so a published financial result that turned out to be
wrong **could not be corrected by anybody** — not through a screen, not through the API. M9 built
the route and its dual-control command; nothing could reach them.

The owner's decision: **the accountant prepares, the manager approves.** The accountant is the
person who published the result and notices the error; the manager carries responsibility for
changing what a trader has already been told.

**The split is enforced by the command, not by these grants.** `_refuse_a_single_human` compares
the two actor ids, so a person holding both permissions is still refused —
`tests/integration/test_publication_correction.py` has asserted that since M9. Granting them to two
roles is what makes the control *reachable*; it is not what makes it safe.

## Activating a bank profile version

`bank_profile.activate_version` was seeded by `20260816_0014` with no grant at all — that migration
says in terms that it withheld the row because the owner had not chosen, and that borrowing a
neighbouring permission would have decided it silently. The owner has now chosen:
**`business_admin`.**

Not the accountant, and the reason is the same shape as `20260828_0027`'s: a profile version
carries the transfer limits, the cutoff time and the file rules, so it changes how *every* payment
is built. The person who creates payments should not be the one who changes the rules they are
built under.

## Grants only, no permissions

All three codes already exist — `20260801_0008` seeded the two correction permissions and
`20260816_0014` seeded the activation one. This revision inserts `role_permissions` rows and
nothing else, which is why it has no `PERMISSIONS` tuple: re-seeding a code that exists would be a
no-op that reads as though the permission were new here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0045"
down_revision: str | Sequence[str] | None = "20260913_0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tuples in the shape `20260801_0008`'s `ROLE_PERMISSIONS` and `20260828_0027`'s
# `CANCELLATION_GRANTS` use, because `test_rbac_seed_matches_catalogue.py` reads every seeding
# revision and compares the union against the catalogue. A revision expressing its rows differently
# would need a special case in that test, and a comparison with a special case per migration is one
# that stops noticing the next one.
CORRECTION_GRANTS: tuple[tuple[str, str], ...] = (
    # The preparer half: the accountant restates the corrected financial result.
    ("accountant", "payment_attempt.correct_result"),
    # The approver half: the manager is what lets a correction reach the trader.
    ("manager", "payment_publication.correct"),
    # Unrelated to the split, and in the same revision because it is the same owner decision and
    # the same shape of gap — a permission that existed and authorised nobody.
    ("business_admin", "bank_profile.activate_version"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for role, code in CORRECTION_GRANTS:
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
    for role, code in CORRECTION_GRANTS:
        # The grants only. The permissions themselves belong to `20260801_0008` and
        # `20260816_0014`; deleting them here would undo a different revision's work and leave
        # those two unable to downgrade cleanly.
        bind.execute(
            sa.text(
                "DELETE FROM role_permissions WHERE role_id IN "
                "(SELECT id FROM roles WHERE code = :role) AND permission_id IN "
                "(SELECT id FROM permissions WHERE code = :code)"
            ),
            {"role": role, "code": code},
        )
