"""The immutable trader-visible result. `04_Database_Schema.md` §11.9.

M9 slice 5. Thirteen columns, two plain uniques and one partial unique — and **no UPDATE grant at
all**, which is the sentence that makes §11.9's opening word true. It says "Immutable versions of
the trader-visible result/share output", and a table the runtime may UPDATE is immutable only for
as long as nobody writes the UPDATE.

Slice 1 established the shape: `20260829_0028` granted nothing on `payment_attempts`, so
"accepting a candidate does not mark an attempt paid" was a privilege the runtime did not hold
rather than a branch somebody could delete. The same reasoning applies here with more force,
because this is the row a trader is shown as proof.

**`status` is granted by M9 slice 7, not here.** Superseding a publication is what a correction
does, and until a correction exists the runtime should be unable to move a publication out of
`active` at all. A grant issued in advance of the command that needs it is a capability with no
caller — this repository's most-repeated defect, in privilege form.

**The three uniques, and what each one refuses.** `04_Database_Schema.md:1154` gives them verbatim:

    UNIQUE(payment_request_id, publication_version)   two version 3s
    UNIQUE(payment_request_id, content_hash)          republishing an identical snapshot
    uq_active_publication_per_request (partial)       two active publications at once

The second is the interesting one and it only works if the hash covers the *content*. Put
`published_at` or `publication_version` into the hashed payload and the constraint can never fire
— every republication would differ by its clock. `app/commands/payment_publication.py` records why
the payload holds neither, and `SVC-PUBLICATION-002` is the test that would fail if either
returned.

The third is why a trader is never shown two current answers, and it is a partial unique index for
the reason slice 2's two were: a service that reads for an active row and then inserts is wrong,
because two transactions both read nothing.

**`share_file_id` is created here and written by nothing.** The renderer, its font asset and the
file-purpose conflict it opens are slice 5B — see the plan. The column arrives with the table
because §11.9 puts it there, and the route offers no way to ask for a file that does not exist
yet, which is the same enforcement-by-absence slice 3 used for the amount and slice 3B for the
beneficiary.

Revision ID: 20260831_0031
Revises: 20260830_0030
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0031"
down_revision: str | Sequence[str] | None = "20260830_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# §11.9's `status` column, and `status_catalog.yaml` has no `payment_result_publication` aggregate
# to compare them against — document 04 is the only source, so these three are taken from it
# directly. `tests/backend/test_status_catalogue_drift.py` checks the aggregates the catalogue
# names; this one it cannot, and the plan records the gap as an M0 debt rather than hiding it.
PUBLICATION_STATUSES = ("active", "superseded", "revoked")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "payment_result_publications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "payment_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_requests.id", name="fk_publications_request"),
            nullable=False,
        ),
        sa.Column("publication_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        # §11.9: "Exact trader-visible fields". Everything the hash covers and nothing else — the
        # actor, the time and the version are columns beside it, not entries inside it.
        sa.Column("summary_payload", postgresql.JSONB(), nullable=False),
        # Written by no command in this slice. See the module docstring.
        sa.Column(
            "share_file_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("file_objects.id", name="fk_publications_share_file"),
            nullable=True,
        ),
        sa.Column(
            "primary_evidence_link_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("confirmed_evidence_links.id", name="fk_publications_evidence"),
            nullable=True,
        ),
        # CHAR(64), which is `unversioned_digest`'s width. The versioned form is 67 and would not
        # fit — the same trade M6's batch hash records in `app/core/hashing.py`.
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column(
            "published_by_admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", name="fk_publications_published_by"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "supersedes_publication_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payment_result_publications.id", name="fk_publications_supersedes"),
            nullable=True,
        ),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            f"status IN ({_quoted(PUBLICATION_STATUSES)})", name="status_value"
        ),
        sa.CheckConstraint("publication_version > 0", name="version_positive"),
        # §11.9's `correction_reason` note in one line: "Required when superseding". Both
        # directions, because a reason attached to nothing is as misleading as a supersession with
        # no reason — slice 2 closed the same shape on `replaces_link_id`.
        sa.CheckConstraint(
            "(supersedes_publication_id IS NULL AND correction_reason IS NULL)"
            " OR "
            "(supersedes_publication_id IS NOT NULL AND correction_reason IS NOT NULL)",
            # Short: `ck_payment_result_publications_` already spends 31 of PostgreSQL's 63 bytes
            # and the identifier gate refuses anything it would truncate silently.
            name="supersession_needs_a_reason",
        ),
        sa.CheckConstraint(
            "supersedes_publication_id IS NULL OR supersedes_publication_id <> id",
            name="no_self_supersession",
        ),
        sa.UniqueConstraint(
            "payment_request_id",
            "publication_version",
            name="uq_publication_version_per_request",
        ),
        sa.UniqueConstraint(
            "payment_request_id", "content_hash", name="uq_publication_content_per_request"
        ),
    )

    # `04_Database_Schema.md:1156`, predicate verbatim. One current answer per request, enforced
    # where two concurrent publishes cannot both win.
    op.create_index(
        "uq_active_publication_per_request",
        "payment_result_publications",
        ["payment_request_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # No GRANT statement, and its absence is the immutability. `020-runtime-roles.sql` grants
    # SELECT and INSERT by default and nothing more, so a runtime role can create a publication
    # and can never alter one. Slice 7 adds `GRANT UPDATE (status)` when superseding exists.


def downgrade() -> None:
    op.drop_index("uq_active_publication_per_request", table_name="payment_result_publications")
    op.drop_table("payment_result_publications")
