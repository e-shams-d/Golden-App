"""The first grant that lets the runtime write a payment result. No new table.

M9 slice 3. `04_Database_Schema.md` §11.3 created every one of these columns in M6 and left them
unwritten; this revision is the privilege, and nothing else.

**Why a migration with no `create_table` is the right shape.** M6 built
`bank_tracking_number`, `bank_result_at`, `failure_code`, `failure_reason`,
`confirmed_by_admin_user_id` and `confirmed_at` against doc 04 `:915` and granted the runtime no
UPDATE on any of them, because M6 knew none of those facts. Two milestones have since passed with
the columns present and unwritable — which is what made "accepting a candidate does not mark an
attempt paid" enforceable by PostgreSQL in `20260829_0028` rather than by a branch somebody could
delete. This revision ends that deliberately, for exactly the columns a confirmation writes.

**What stays unwritable, and it is the point.** `amount_irr`, `beneficiary_name_snapshot`,
`beneficiary_iban_snapshot`, `bank_profile_version_id`, `attempt_number`, `attempt_type`,
`payment_request_revision_id` and both self-referencing lineage columns. A confirmation records
what the bank did; it cannot restate what was sent. `SEC-CONFIRM-001` reads that back from
`information_schema` as the runtime role, which is the assertion a behavioural test cannot make.

**`record_version` is in the grant because `compare_and_swap` writes it.** A confirmation takes
`If-Match` — doc 05 `:1566` shows it — and the optimistic-concurrency helper needs to move the
version in the same statement it moves the status.

Revision ID: 20260830_0030
Revises: 20260830_0029
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0030"
down_revision: str | Sequence[str] | None = "20260830_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Exactly what a paid or failed confirmation writes, and nothing adjacent. `updated_at` is here
# because every mutation touches it; the snapshots are not, at any price.
GRANTED_COLUMNS = (
    "status",
    "bank_tracking_number",
    "bank_result_at",
    "failure_code",
    "failure_reason",
    "confirmed_by_admin_user_id",
    "confirmed_at",
    "record_version",
    "updated_at",
)

# Named so the downgrade is exact rather than a guess, and so a reader can see at a glance that
# this revision widens `payment_attempts` and touches nothing else.
TABLE = "payment_attempts"


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
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(sa.text(f'GRANT UPDATE ({columns}) ON public."{TABLE}" TO "{role}"'))


def downgrade() -> None:
    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(sa.text(f'REVOKE UPDATE ({columns}) ON public."{TABLE}" FROM "{role}"'))
