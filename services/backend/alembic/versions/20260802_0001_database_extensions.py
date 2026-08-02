"""Enable the PostgreSQL extensions every later table depends on.

Revision ID: 20260802_0001
Revises: 20260720_0001
Create Date: 2026-08-02

Both are required by `04_Database_Schema.md` section 3.1. Kept as their own revision so
they exist before the first table that needs them; folding them into a table revision makes
that revision fail on a fresh database for a reason unrelated to its own content.

`citext` supplies case-insensitive text for identity columns, where two spellings must not
become two accounts. It is not built in and a table using CITEXT fails without it.

`pgcrypto` supplies cryptographic functions such as `digest()`. It is deliberately **not**
the source of `gen_random_uuid()`: that has been core PostgreSQL since 13, verified against
the pinned `postgres:16.14-alpine3.24` image with only `plpgsql` installed. Recording the
reason matters because a future reader who believes UUID generation depends on pgcrypto
will draw the wrong conclusion about whether it can be dropped.

Managed-environment fallback: if the migrator role lacks CREATE privilege on the database,
an administrator provisions both extensions once, out of band, before the first migration
runs. `IF NOT EXISTS` then makes this revision a no-op rather than a failure. Provisioning
them out of band is the norm on managed PostgreSQL; the failure mode to avoid is granting
the migrator superuser purely so this revision can run.

Downgrade policy is forward-fix. Dropping an extension would cascade into every column
that depends on its types, so `downgrade()` deliberately does nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260802_0001"
down_revision: str | Sequence[str] | None = "20260720_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def downgrade() -> None:
    pass
