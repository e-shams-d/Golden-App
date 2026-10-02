"""The grant `incoming_payment_matches` was built without. No new table.

Found by F-21: the integration suites built the app with `owner_url`, and the owner can do
anything, so no test could see this. Running the suite as the application role turned
thirteen existing tests red at once — all of them on one statement, and all of them
correct about it.

**`record_version` was the one column the confirmation writes that nobody granted.**
`20260909_0040` enumerated nine columns for this table and left it out; `20260910_0041`
added `confirmation_status` and did not notice. So `UPDATE incoming_payment_matches SET
confirmation_status=…, confirmed_amount_irr=…, record_version=…` — the statement
`compare_and_swap` builds for every confirmation and every rejection — was refused by
PostgreSQL in any deployment with the runtime roles in force, which is every real one.

Twenty of the twenty-one tables carrying `record_version` already grant it to the
application and worker roles. This table was the only one that did not.

**This exact omission has been made and corrected once before.** `20260830_0030` exists
for no other reason, and says so in its own docstring: *"`record_version` is in the grant
because `compare_and_swap` writes it."* A fact learned twice and forgotten twice is not a
thing to remember harder — `tests/integration/test_record_version_is_writable.py` reads
`information_schema` as the runtime role and refuses any table that omits it.

Revision ID: 20261002_0046
Revises: 20260914_0045
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_0046"
down_revision: str | Sequence[str] | None = "20260914_0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# One column. Everything else this table exposes was granted deliberately in `0040` and
# `0041`, and widening any of it here would be a second decision hiding inside a fix.
GRANTED_COLUMNS = ("record_version",)

TABLE = "incoming_payment_matches"


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
