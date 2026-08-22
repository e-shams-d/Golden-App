"""Four column grants, so an export can be downloaded and marked sent.

M7 slice 4. `20260822_0021` granted nothing at all, which is what has kept `export_type`
unwritable and a preview unpromotable. This widens that by exactly four columns and no more.

**Column-level, and the list is the whole point.** A table-level `GRANT UPDATE` would also permit
rewriting `export_type`, `batch_approval_id`, `content_hash` and `file_sha256_hash` — which is to
say rewriting *which file this is* and *what it claims to contain*. §1 of
`FINANCIAL_INTEGRITY_BASELINE.md` forbids promoting a preview into a final artifact, and the
enforcement of that has been the absence of a grant rather than a rule somebody remembers. It
stays that way here.

The four:

- `status` — `validated` → `downloaded` → `sent_to_bank_marked`, and `quarantined` when a
  revalidation fails on the download path (`05_API_Specification.md:1514`).
- `downloaded_at` — set on the first successful download.
- `sent_to_bank_marked_at` and `sent_to_bank_marked_by_admin_user_id` — the pair mark-sent writes.
  Granted together because they are written together; either alone would record half of who did
  what.

**Not granted, and named so the omission is visible:** `submission_channel` and `note`. §15.7 lists
both among the seven things mark-sent "records", and §11.8 gives the table no column for either —
so they are recorded in the audit row, which is where a fact with no column belongs. Inventing two
columns document 04 does not define would be the schema drift this repository's gates exist to
catch, in the one milestone where the schema is the evidence.

`tests/integration/test_export_table_privileges.py::test_the_columns_a_later_slice_will_need_are_not_granted_yet`
is **deleted** by this slice rather than amended. Its own docstring says so: a test left passing
against a narrower claim is worse than no test, and the same choice was made when `20260821_0019`
granted the allocation's release pair.

Revision ID: 20260822_0022
Revises: 20260822_0021
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0022"
down_revision: str | Sequence[str] | None = "20260822_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Exactly what download and mark-sent write. Every other column on this table stays frozen.
GRANTED_COLUMNS = (
    "status, downloaded_at, sent_to_bank_marked_at, sent_to_bank_marked_by_admin_user_id"
)


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
                f"GRANT UPDATE ({GRANTED_COLUMNS}) ON public.\"bank_excel_exports\" TO \"{role}\""
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    for role in _runtime_roles():
        bind.execute(
            sa.text(
                f"REVOKE UPDATE ({GRANTED_COLUMNS}) ON public.\"bank_excel_exports\" "
                f'FROM "{role}"'
            )
        )
