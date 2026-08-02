"""Create center_profile, the deployment's own mutable aggregate.

Separate from the integrity tables that follow so the exemplar aggregate and the
machinery that records changes to it can be reasoned about, and reverted,
independently.

CHECK constraints carry the **bare** name, exactly as the model passes it to
`named_check`. `op.create_table` applies `Base.metadata`'s naming convention, and
the `ck` rule interpolates `%(constraint_name)s`, so a full `ck_center_profile_...`
here would produce `ck_center_profile_ck_center_profile_...`. The index and
primary key take their full names, because those rules do not interpolate.

Forward-fix policy: this table is mutable and has no dependants yet, so a
downgrade that drops it is honest. Append-only tables get no such downgrade.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0003"
down_revision: str | None = "20260801_0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "center_profile",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("legal_name", sa.String(length=300), nullable=True),
        sa.Column(
            "default_currency",
            sa.String(length=3),
            server_default=sa.text("'IRR'"),
            nullable=False,
        ),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'Asia/Tehran'"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("record_version", sa.BigInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "default_currency = 'IRR'",
            name="default_currency_is_irr",
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        sa.PrimaryKeyConstraint("id", name="pk_center_profile"),
    )
    # A partial unique index, because PostgreSQL accepts WHERE only on an index
    # and not on a UNIQUE constraint. This is what makes "one active profile" a
    # database guarantee rather than an application convention.
    op.create_index(
        "uq_center_profile_one_active",
        "center_profile",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_center_profile_one_active", table_name="center_profile")
    op.drop_table("center_profile")
