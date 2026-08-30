"""The authoritative segment-to-attempt relationship. `04_Database_Schema.md` §12.6.

M9 slice 2. Eleven columns, one plain unique, and **two partial unique indexes that are the
slice**: §12.6 at `:1297` gives them verbatim, and they are what turn §17 `:1115`'s cardinality
rules from prose into something the database refuses.

    one active primary per attempt      -> uq_attempt_active_primary_evidence
    one active primary target per segment -> uq_segment_active_primary_attempt
    supplementary unbounded             -> no index at all

The third rule is expressed by an **absence**, which is why it needs saying: a reader looking for
three constraints and finding two would reasonably think one was forgotten.

**`revoked`, not `voided` — and the catalogue itself records why this needed deciding.**
`command_catalog.yaml`'s `evidence_link.revoke` row carries
`status: blocked_by_voided_vs_revoked_status_conflict`. Documents 06 and 08 say `revoked`;
documents 04 and 05 say `voided`; `status_catalog.yaml` holds `revoked` as canonical with `voided`
as a **provisional alias pending schema/API reconciliation**.

Settled by the precedent DOC-CONFLICT-016 set for `bank_export`: the status catalogue wins for the
enforced CHECK, because the status-drift gate holds every CHECK to its aggregate exactly. So the
column admits the canonical three and nothing else. The **route path stays `/void`** — that is
document 05's contract and renaming it is a breaking change the oasdiff gate would refuse. A path
and a stored status that differ in spelling is untidy; untidy is cheaper than either an unapproved
schema value or a broken contract. Documents 04 and 05 are owed an editorial fix.

M8 slice 4 set the precedent for building against a `blocked` catalogue row rather than stopping at
it: `receipt_segment.create_crop` carried `status: blocked_by_coordinate_rotation_contract` and the
slice resolved the blocker and recorded it. A `status` field on a catalogue row names a blocker, not
a prohibition.

**Grants: `status` and `published_to_trader_at`, and nothing else.** Which attempt, which segment,
which type, who confirmed it and when are what the row *is* — §12.6 at `:1306` says replacement
"never deletes or overwrites the old relationship", and a row whose subject could be rewritten
would make that guarantee meaningless. `replaces_link_id` and `replacement_reason` are written at
insert on the *new* row and never afterwards.

**No revocation-reason column, deliberately.** §22.3 requires a reason and §12.6 gives the table no
column for one. It goes on the audit row, where slice 1 put a rejection's reason for the same
reason: inventing a column two catalogues do not describe is the drift this milestone opened by
promising not to do.

Revision ID: 20260830_0029
Revises: 20260829_0028
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0029"
down_revision: str | Sequence[str] | None = "20260829_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `status_catalog.yaml`'s `confirmed_evidence_link` aggregate. `voided` is an alias there and is
# **not** admitted: a deprecated spelling that never broadens meaning and fails closed is the rule
# `app/security/permission_catalogue.py` already records for document 05's permission spellings.
LINK_STATUSES = ("active", "replaced", "revoked")

# §12.6 at `:1284`. Not a lifecycle — the kind of evidence, fixed at insert, and the third column
# of the plain unique below.
LINK_TYPES = ("primary", "supplementary")

# The lifecycle, and the one timestamp a later slice writes. Everything else is the row's subject.
GRANTED_COLUMNS = ("status", "published_to_trader_at")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


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
    op.create_table(
        "confirmed_evidence_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "payment_attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_attempts.id", name="fk_evidence_links_attempt"),
            nullable=False,
        ),
        sa.Column(
            "receipt_segment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receipt_segments.id", name="fk_evidence_links_segment"),
            nullable=False,
        ),
        sa.Column("link_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        # §12.6: "Human actor", NOT NULL. There is no system path to this table — §17 `:1106`
        # requires an actor and a reason on every link, and a nullable column here would be an
        # invitation to write one without either.
        sa.Column(
            "confirmed_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_evidence_links_confirmed_by"),
            nullable=False,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        # Self FK. The chain a replacement leaves behind, and the reason §12.6 can promise that
        # replacement never deletes: the old row is still there and the new one points at it.
        sa.Column(
            "replaces_link_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("confirmed_evidence_links.id", name="fk_evidence_links_replaces"),
            nullable=True,
        ),
        sa.Column("replacement_reason", sa.Text(), nullable=True),
        # Written by M9's publication slice. Nullable and unwritten here.
        sa.Column("published_to_trader_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"link_type IN ({_quoted(LINK_TYPES)})", name="link_type_value"),
        sa.CheckConstraint(f"status IN ({_quoted(LINK_STATUSES)})", name="status_value"),
        # Not in §12.6, and it closes the same shape slice 1 closed on `resolved_at`: a row that
        # says it replaced something must say why, and a row that replaced nothing must not carry
        # a replacement reason. Decidable by the database, unlike a rule left to a service.
        sa.CheckConstraint(
            "(replaces_link_id IS NULL AND replacement_reason IS NULL)"
            " OR "
            "(replaces_link_id IS NOT NULL AND replacement_reason IS NOT NULL)",
            # Short because `ck_confirmed_evidence_links_` already spends 28 of PostgreSQL's 63
            # bytes and the identifier gate refuses anything it would truncate silently.
            name="replacement_needs_a_reason",
        ),
        sa.CheckConstraint(
            "replaces_link_id IS NULL OR replaces_link_id <> id",
            name="a_link_does_not_replace_itself",
        ),
        # §12.6 at `:1295`. The plain unique: the same pair may hold a primary *and* a
        # supplementary link, and both may exist at once — which is what makes `link_type` part
        # of it rather than a column beside it.
        sa.UniqueConstraint(
            "payment_attempt_id",
            "receipt_segment_id",
            "link_type",
            name="uq_evidence_link_attempt_segment_type",
        ),
    )

    # §12.6 at `:1297`, both predicates verbatim. These two are the slice: without them
    # §17 `:1115`'s cardinality is a sentence in a document, and two accountants confirming the
    # same attempt from two screens both succeed.
    op.create_index(
        "uq_attempt_active_primary_evidence",
        "confirmed_evidence_links",
        ["payment_attempt_id"],
        unique=True,
        postgresql_where=sa.text("link_type = 'primary' AND status = 'active'"),
    )
    op.create_index(
        "uq_segment_active_primary_attempt",
        "confirmed_evidence_links",
        ["receipt_segment_id"],
        unique=True,
        postgresql_where=sa.text("link_type = 'primary' AND status = 'active'"),
    )

    bind = op.get_bind()
    columns = ", ".join(GRANTED_COLUMNS)
    for role in _runtime_roles():
        bind.execute(
            sa.text(
                f'GRANT UPDATE ({columns}) ON public."confirmed_evidence_links" TO "{role}"'
            )
        )


def downgrade() -> None:
    op.drop_index("uq_segment_active_primary_attempt", table_name="confirmed_evidence_links")
    op.drop_index("uq_attempt_active_primary_evidence", table_name="confirmed_evidence_links")
    op.drop_table("confirmed_evidence_links")
