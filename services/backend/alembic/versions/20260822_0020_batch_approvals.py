"""The manager's decision on one exact version, with separation enforced by the schema.

`04_Database_Schema.md` §11.7 gives `batch_approvals` ten columns and three SQL statements. This
revision adds those, and two columns document 04 does not list, for a reason worth stating fully
because it is the whole point of the slice.

**Why a guard in the database at all.** `FINANCIAL_INTEGRITY_BASELINE.md` §5 is Resolved —
Approved and requires `finalizer != approver` "at the command layer **and** by a
database-enforceable guard or transactional constraint/trigger whose race behavior is tested".
A service check alone loses to concurrency: two requests can both read "the finalizer is Ali, the
approver is Sara", both pass, and both write. §2 of that document says the same thing about the
allocation, and M6 built the partial unique index rather than argue with it.

**Why not a trigger.** §11.7 offers "a deferred database trigger or the application transaction".
There is not one trigger in this repository, and introducing the first one for this would put
business logic in a place no test in the tree currently reads and no reviewer currently looks.
The relational answer costs two columns and no new machinery.

**How the guard works.** A CHECK cannot reach another table, so the two actors it must compare
have to be on the same row. `batch_approvals` therefore carries the version's finalizer and
preparer, each `NOT NULL`, each tied to the truth by a composite foreign key:

    (payment_batch_version_id, version_finalized_by_admin_user_id)
        -> payment_batch_versions (id, finalized_by_admin_user_id)

The copy cannot be wrong, because the foreign key refuses any pair the version does not actually
have. The copy cannot go stale either: `20260820_0017` grants the runtime roles UPDATE on exactly
`(status, superseded_at)` of `payment_batch_versions`, so neither actor column is writable by the
process that would have to change it. And `NOT NULL` on the finalizer means a version nobody
finalized cannot be approved at all — a draft has no finalizer, and that is the correct refusal
rather than an accident of nullability.

Then the comparison is a plain CHECK on one row, evaluated per insert, immune to what any other
transaction read a moment earlier.

**The hash is tied the same way, and needs no new column.** §11.7 says "a deferred database
trigger or the application transaction must verify that an approval hash equals the referenced
version hash". `approved_content_hash` is already a document-04 column, so a composite foreign key
to `(id, content_hash)` does it. It is `NULL` for a rejection, and under MATCH SIMPLE a foreign
key with a NULL member is not enforced — which is exactly right here: a rejection carries no hash
and there is nothing to verify. An approval carries one and cannot name a hash its version does
not have. That is `TRACE-APPROVAL-001` enforced by the schema rather than by a convention.

**Three unique constraints on the parent, which the foreign keys above require.** None of them
constrains anything new — `id` is already the primary key, so `(id, x)` is unique for any `x`.
They exist so PostgreSQL will accept the composite references. `20260820_0017` added
`uq_batch_version_pair` for the same reason and document 04 names that one at `:1555`.

**No grants.** `infra/postgres/bootstrap/020-runtime-roles.sql:95-96` sets the default for new
tables to `SELECT, INSERT` and nothing else, deliberately fail-closed. §11.7 says
"Approved/rejected rows are never updated", so the default is already the policy and adding an
UPDATE grant is the only way to break it. `tests/integration/test_approval_table_privileges.py`
asserts that rather than trusting this paragraph — the bootstrap is a file somebody can edit.

Revision ID: 20260822_0020
Revises: 20260821_0019
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0020"
down_revision: str | Sequence[str] | None = "20260821_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# §11.7: "`approved`, `rejected`". Two values, and the status drift gate holds this list to
# `docs/governance/status_catalog.yaml` rather than to this file.
DECISIONS_SQL = "'approved', 'rejected'"

# §11.7 verbatim. Kept as one string so the shape it encodes stays readable: an approval names a
# hash and needs no reason, a rejection names a reason and must not name a hash. The second half
# is what stops a rejection from quietly carrying an approval's evidence.
DECISION_SHAPE_SQL = """
(decision = 'approved' AND approved_content_hash IS NOT NULL)
OR
(decision = 'rejected' AND approved_content_hash IS NULL AND reason IS NOT NULL)
"""


def upgrade() -> None:
    # The three references the composite foreign keys below need. Added first, because a foreign
    # key cannot be created against a column pair PostgreSQL does not already know is unique.
    op.create_unique_constraint(
        op.f("uq_batch_version_finalizer_pair"),
        "payment_batch_versions",
        ["id", "finalized_by_admin_user_id"],
    )
    op.create_unique_constraint(
        op.f("uq_batch_version_preparer_pair"),
        "payment_batch_versions",
        ["id", "created_by_admin_user_id"],
    )
    op.create_unique_constraint(
        op.f("uq_batch_version_hash_pair"),
        "payment_batch_versions",
        ["id", "content_hash"],
    )

    op.create_table(
        "batch_approvals",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("payment_batch_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("decided_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("approved_content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "authentication_context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # The two columns document 04 does not list. `tests/backend/test_approval_schema.py`
        # records them as named deviations with this revision's docstring as the authority, so
        # they cannot spread and cannot be mistaken for a transcription error.
        sa.Column(
            "version_finalized_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "version_created_by_admin_user_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.CheckConstraint(
            f"decision IN ({DECISIONS_SQL})", name=op.f("ck_batch_approvals_decision_value")
        ),
        sa.CheckConstraint(DECISION_SHAPE_SQL, name=op.f("ck_batch_approvals_decision_shape")),
        # `FINANCIAL_INTEGRITY_BASELINE.md` §5, the half a service check cannot hold under
        # concurrency. SEC-APPROVAL-001.
        sa.CheckConstraint(
            "decided_by_admin_user_id <> version_finalized_by_admin_user_id",
            name=op.f("ck_batch_approvals_approver_is_not_finalizer"),
        ),
        # The stricter of the two readings of `12_Security_RBAC_Audit.md:1111`, "actor is not the
        # version finalizer/preparer". G-2 and DOC-CONFLICT-055 record that the owner may mean
        # only the finalizer; if they do, this one constraint is dropped and nothing else moves.
        # SEC-APPROVAL-002.
        sa.CheckConstraint(
            "decided_by_admin_user_id <> version_created_by_admin_user_id",
            name=op.f("ck_batch_approvals_approver_is_not_preparer"),
        ),
        sa.CheckConstraint(
            "approved_content_hash IS NULL OR approved_content_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_batch_approvals_hash_is_lowercase_hex"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_batch_version_id"],
            ["payment_batch_versions.id"],
            name="fk_batch_approvals_version",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_admin_user_id"],
            ["admin_users.id"],
            name="fk_batch_approvals_decided_by",
        ),
        # The three that make the guard real. Each says: this copy is the version's own value,
        # not something the caller supplied.
        sa.ForeignKeyConstraint(
            ["payment_batch_version_id", "version_finalized_by_admin_user_id"],
            ["payment_batch_versions.id", "payment_batch_versions.finalized_by_admin_user_id"],
            name="fk_batch_approvals_version_finalizer",
        ),
        sa.ForeignKeyConstraint(
            ["payment_batch_version_id", "version_created_by_admin_user_id"],
            ["payment_batch_versions.id", "payment_batch_versions.created_by_admin_user_id"],
            name="fk_batch_approvals_version_preparer",
        ),
        sa.ForeignKeyConstraint(
            ["payment_batch_version_id", "approved_content_hash"],
            ["payment_batch_versions.id", "payment_batch_versions.content_hash"],
            name="fk_batch_approvals_approved_hash",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batch_approvals")),
        # §11.7's first statement. One decision per version, decided by the database — which is
        # also what makes two concurrent approvals produce one row rather than two.
        # CON-APPROVAL-001.
        sa.UniqueConstraint(
            "payment_batch_version_id", name=op.f("uq_batch_approvals_one_per_version")
        ),
        # §11.7's second statement. The pair a later composite reference would need; document 04
        # states it, so it is created as stated.
        sa.UniqueConstraint(
            "id", "payment_batch_version_id", name=op.f("uq_batch_approvals_version_pair")
        ),
    )


def downgrade() -> None:
    op.drop_table("batch_approvals")
    op.drop_constraint(
        op.f("uq_batch_version_hash_pair"), "payment_batch_versions", type_="unique"
    )
    op.drop_constraint(
        op.f("uq_batch_version_preparer_pair"), "payment_batch_versions", type_="unique"
    )
    op.drop_constraint(
        op.f("uq_batch_version_finalizer_pair"), "payment_batch_versions", type_="unique"
    )
