"""Record who finalized a batch version, because the approved separation rule needs it.

One nullable column and one column-level grant. The reason is longer than the change.

**`FINANCIAL_INTEGRITY_BASELINE.md` §5 is Resolved — Approved** (DOC-CONFLICT-021) and requires
that "the **recorded finalizer actor** must differ from the approver actor for the exact
immutable batch version", enforced "by the command/domain layer **and by a database-enforceable
guard or transactional constraint/trigger whose race behavior is tested**".
`12_Security_RBAC_Audit.md:1111` states it again as an approval guard, and `:2370` and `:2471`
list it as a required test.

**The word "finalizer" appears nowhere in document 04 or document 05.** §11.5 gives
`payment_batch_versions` a `created_by_admin_user_id` and no finalizer column; §11.7 gives
`batch_approvals` a `decided_by_admin_user_id`. So the documented schema can name the *preparer*
and the *approver* and not the finalizer — and a database-enforceable guard cannot reference a
column that does not exist.

**Why that is a hole rather than a redundancy.** `payment_batch_version.create` and
`payment_batch_version.finalize` are separate rows in `permission_catalog.yaml`, both defaulting
to `accountant`, so one accountant can prepare a version and another can finalize it. Comparing
the approver against `created_by_admin_user_id` alone would pass for exactly the person who
finalized it — and §5 says the rule "is not configurable off".

**The precedent is slice 2's, one notch larger.** `payment_attempt_allocations` is an entire
table document 04 never mentions, created because `FINANCIAL_INTEGRITY_BASELINE.md:34-49`
approves it. Adding one column on the same authority is the same decision.
`DOC-CONFLICT-055` records it, G-11 asks the owner to put it in document 04 §11.5, and
`tests/backend/test_batch_schema.py` carries it as a **named** deviation so it cannot spread and
cannot be mistaken for a transcription error.

**Nullable, and that is the honest type.** A draft has no finalizer. `NOT NULL` would force
`create_batch` to invent one — most likely the creator, which is the very conflation this column
exists to prevent.

**M6 persists; M7 enforces.** This migration makes the comparison *possible*. The guard itself,
and the concurrent finalize/approve race test §5 demands, belong to the milestone that has an
approver to compare against.

The grant is column-level and additive: PostgreSQL accumulates column privileges, so this adds
`finalized_by_admin_user_id` to the `(status, superseded_at)` set `20260820_0017` granted without
widening anything else. A table-level `UPDATE` here would also permit rewriting `content_hash`,
which is the value a manager's approval is bound to.

Downgrade drops the column. Honest only while no version has been finalized, on the terms
`20260801_0012:44-46` records.

Revision ID: 20260821_0018
Revises: 20260820_0017
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260821_0018"
down_revision: str | Sequence[str] | None = "20260820_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Only the new column. `status` and `superseded_at` were granted by `20260820_0017` and stay
# granted; naming them again would be harmless and would also hide which migration owns which
# privilege.
NEW_COLUMN_GRANT = "finalized_by_admin_user_id"


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
            f"Migration {revision} grants on a mutable column and these roles are "
            f"not set: {', '.join(missing)}."
        )
    return tuple(str(value) for value in configured.values())


def upgrade() -> None:
    op.add_column(
        "payment_batch_versions",
        sa.Column("finalized_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_batch_versions_finalized_by",
        "payment_batch_versions",
        "admin_users",
        ["finalized_by_admin_user_id"],
        ["id"],
    )

    bind = op.get_bind()
    for role in _runtime_roles():
        bind.execute(
            sa.text(
                f"GRANT UPDATE ({NEW_COLUMN_GRANT}) "
                f'ON public."payment_batch_versions" TO "{role}"'
            )
        )


def downgrade() -> None:
    op.drop_constraint(
        "fk_batch_versions_finalized_by", "payment_batch_versions", type_="foreignkey"
    )
    op.drop_column("payment_batch_versions", "finalized_by_admin_user_id")
