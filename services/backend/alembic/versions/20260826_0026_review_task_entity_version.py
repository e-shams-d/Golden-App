"""Pin a review task to the version of the thing it is about.

M8 slice 7. One nullable column on `manual_review_tasks`, and the reason it exists is §16.5.

**§16.5 asks for a verification and names no table.** "Before evidence can be included in
publication, the operator must verify that the crop does not reveal unrelated names, IBANs, amounts,
tracking references, or transactions." `04_Database_Schema.md` gives that verification no column and
no table; a search for a review or verification table finds nothing.

**M0 has already said where it goes.** `manual_review_tasks.task_type` admits
`segment_privacy_review` — one of exactly four types slice 3 took from the approved list — so the
work item is a review task. And a resolved task already records three of the four facts
`SVC-PRIVACY-001` needs: the actor (`resolved_by_admin_user_id`), the time (`resolved_at`) and the
subject (`entity_id`).

**What it cannot say is *which version* of that subject.** `record_version` on this table is the
task's own version, not its subject's. `SVC-PRIVACY-001` requires the verification to be per segment
version, because a segment edited after being verified is unverified again — otherwise the record
attests to something that no longer exists. So a task needs to name the version it was about, and
this column is that.

**Not invented: copied.** `audit_logs.entity_record_version` is the same column for the same reason,
and has existed since M2. Moving an established pattern to the table that needs it is a smaller
decision than a new table with a new permission, a new command row and a new audit action — and
`manual_review.resolve` is already seeded and audited.

**Nullable, and written at resolution rather than at opening.** Nullable because a task about
something with no version — a bundle, an attempt — honestly has none, and because tasks that already
exist cannot claim one retroactively.

Written at *resolution* because that is when the human judgement happens: the operator verifies the
crop in front of them, and the version they verified is the one it has at that moment. Capturing it
when the task was raised would record the version somebody was *asked* about, which is a different
fact and the wrong one — a segment re-rendered between the request and the review would leave a
record attesting to a version nobody looked at.

That needs an UPDATE grant, which the first draft of this migration withheld on the grounds that the
value never moves. It does move once, from NULL to the verified version, and the protection against
moving twice is elsewhere and stronger: `PERMITTED_TRANSITIONS` in
`app/commands/manual_review_task.py` draws no arrow out of `resolved`, and
`ck_manual_review_tasks_resolved_requires_a_disposition` refuses a resolved row that loses its
disposition.

**Why not columns on `receipt_segments`.** A verification is an event — a person looked at one
version of one crop at one moment — and events belong in rows, not in mutable columns on their
subject. Columns hold only the latest; a segment can be verified, edited and verified again, and the
history of that is what an auditor asks for. Slice 2 also granted the runtime UPDATE on almost
nothing there deliberately, and three new writable columns would have argued with that.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0026"
down_revision: str | Sequence[str] | None = "20260824_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _runtime_roles() -> tuple[str, ...]:
    """The configured application and worker roles.

    Read from settings rather than written literally: slice 1 hardcoded `gold_app_runtime` here and
    a fresh database answered `role does not exist`. The roles are deployment configuration and this
    file is not the place that decides them.
    """

    from app.core.config import load_settings

    settings = load_settings()
    configured = {
        "APP_DB_ROLE": settings.app_db_role,
        "WORKER_DB_ROLE": settings.worker_db_role,
    }
    return tuple(sorted({role for role in configured.values() if role}))


def upgrade() -> None:
    op.add_column(
        "manual_review_tasks",
        sa.Column("entity_record_version", sa.BigInteger(), nullable=True),
    )
    bind = op.get_bind()
    for role in _runtime_roles():
        bind.execute(
            sa.text(
                "GRANT UPDATE (entity_record_version) ON public.\"manual_review_tasks\" "
                f'TO "{role}"'
            )
        )
    # Positive when present. A version of zero or below is not a row anybody wrote —
    # `record_version` starts at 1 everywhere in this schema — so admitting one would let a task
    # claim a subject version that cannot exist.
    op.create_check_constraint(
        "entity_record_version_is_positive",
        "manual_review_tasks",
        "entity_record_version IS NULL OR entity_record_version > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_manual_review_tasks_entity_record_version_is_positive",
        "manual_review_tasks",
        type_="check",
    )
    op.drop_column("manual_review_tasks", "entity_record_version")
