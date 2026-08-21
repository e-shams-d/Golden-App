"""Widen two grants so an allocation can be released and a batch cancelled.

No new tables, no new columns. Two column-level grants that `20260820_0017` deliberately withheld,
and the reason it withheld them is the reason this migration exists rather than the grants having
been there all along.

**`payment_attempt_allocations` had no UPDATE grant at all.** Slice 2 created `released_at` and
`release_reason` and granted nothing, so
`tests/integration/test_batch_creation.py::test_release_is_not_possible_yet` could prove — through
the runtime role, not through a comment — that release did not exist yet. That test now becomes
wrong, and it is deleted in the same commit rather than left passing against a narrower claim.
Granting the pair early would have been a permission with nothing behind it, which is how
`payment_batch.cancel_draft` came to be approved and seeded with no command (G-4).

**Column-level, not table-level.** `GRANT UPDATE (released_at, release_reason)` is what release
needs and nothing more. A table-level grant would also permit rewriting `payment_attempt_id`,
`payment_batch_version_id` and `payment_batch_item_id` — that is, rewriting *which* allocation
this row is, which would let a release be retargeted at a different attempt after the fact. The
pair is enforced together by `ck_payment_attempt_allocations_release_pair_complete`, so a release
cannot record a time without a reason.

**`payment_batches` needs nothing new.** `20260820_0017` already granted
`(status, cancelled_at, cancelled_reason, record_version, updated_at)`, because document 04 §11.4
gives the container those columns and a cancellation was always going to write them. That is the
difference between a grant made for a column that exists and a grant made for a command that does
not: the first is the table's shape, the second is a capability.

**The partial unique index does the rest.** Releasing sets `released_at`, which takes the row out
of `uq_active_allocation_per_attempt`'s predicate — so the attempt becomes allocatable again by
the same mechanism that refused a second allocation while it was active. Nothing here adds a
constraint, because nothing needs one: the index was written to make release possible without
deleting evidence, and this grant is the last piece of that.

Revision ID: 20260821_0019
Revises: 20260821_0018
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0019"
down_revision: str | Sequence[str] | None = "20260821_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The two columns a release writes, and no others.
RELEASE_COLUMNS = "released_at, release_reason"


def _runtime_roles() -> tuple[str, ...]:
    from app.core.config import load_settings

    settings = load_settings()
    configured = {
        "APP_DB_ROLE": settings.app_db_role,
        "WORKER_DB_ROLE": settings.worker_db_role,
    }
    missing = sorted(name for name, value in configured.items() if not value)
    if missing:
        raise RuntimeError(
            f"Migration {revision} grants on mutable columns and these roles are "
            f"not set: {', '.join(missing)}."
        )
    return tuple(str(value) for value in configured.values())


def upgrade() -> None:
    bind = op.get_bind()
    for role in _runtime_roles():
        bind.execute(
            sa.text(
                f"GRANT UPDATE ({RELEASE_COLUMNS}) "
                f'ON public."payment_attempt_allocations" TO "{role}"'
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    for role in _runtime_roles():
        bind.execute(
            sa.text(
                f"REVOKE UPDATE ({RELEASE_COLUMNS}) "
                f'ON public."payment_attempt_allocations" FROM "{role}"'
            )
        )
