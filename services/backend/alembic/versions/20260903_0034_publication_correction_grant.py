"""Superseding a publication becomes possible. `04_Database_Schema.md:1162`.

M9 slice 7B. Creates nothing. One column-level grant, and it is the one `20260831_0031`
deliberately withheld.

Slice 5's migration says why it withheld it, in its own words: "Superseding a publication is what a
correction does, and until a correction exists the runtime should be unable to move a publication
out of `active` at all. A grant issued in advance of the command that needs it is a capability with
no caller." The correction exists now, so the grant arrives with it.

**`status` and nothing else.** §11.9 calls these rows immutable and `:1162` describes the only
change one may undergo: "A correction creates a new publication, marks the previous row
`superseded`". Everything else on the row — the payload, the hash, who published it, what it
supersedes — is what a trader was shown, and a correction that could rewrite any of it would make
"the previous version is preserved" a description of intent rather than of the database.

`summary_payload` and `content_hash` staying unwritable is what makes `SVC-CORRECTION-001`
assertable at all: publication N is read back column by column and only `status` may have moved,
and the reason it cannot be anything else is this list rather than a code branch.

Revision ID: 20260903_0034
Revises: 20260902_0033
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260903_0034"
down_revision: str | Sequence[str] | None = "20260902_0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "payment_result_publications"

# One column. See the module docstring for why the list is not longer.
GRANTED_COLUMNS = ("status",)


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
    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(sa.text(f'GRANT UPDATE ({columns}) ON public."{TABLE}" TO "{role}"'))


def downgrade() -> None:
    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(sa.text(f'REVOKE UPDATE ({columns}) ON public."{TABLE}" FROM "{role}"'))
