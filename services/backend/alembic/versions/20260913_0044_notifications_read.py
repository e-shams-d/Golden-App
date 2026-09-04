"""A notification can be marked read. `05_API_Specification.md:2077`.

M11 slice 1. Two column grants and nothing else — the table, its indexes and its CHECKs were all
built by `20260902_0033`.

**`20260902_0033` withheld this grant deliberately and said so**: "No GRANT. See the module
docstring: nothing marks a notification read yet, and a grant ahead of the command that needs it is
a capability with no caller." The command now exists, so the grant arrives with it. That is the
same discipline in the other direction, and it is why this revision is two columns wide.

**`status` and `read_at`, and nothing else.** Not `title`, not `body`, not `entity_type`, not
`recipient_actor_id`: a notification is a record of what a person was told, and one whose text
could be edited afterwards would be a message that says something different from what was sent. Not
`deduplication_key` either — it is what makes at-least-once delivery produce one message, and a
writable copy is one a redelivery could dodge.

Revision ID: 20260913_0044
Revises: 20260912_0043
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0044"
down_revision: str | Sequence[str] | None = "20260912_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The two facts marking a notification read establishes: that it was read, and when.
GRANTED_COLUMNS = ("status", "read_at")


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
        bind.execute(sa.text(f'GRANT UPDATE ({columns}) ON public."notifications" TO "{role}"'))


def downgrade() -> None:
    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(
            sa.text(f'REVOKE UPDATE ({columns}) ON public."notifications" FROM "{role}"')
        )
