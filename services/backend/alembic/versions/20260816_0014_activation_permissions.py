"""Seed the two activation permissions, granted to nobody.

DOC-CONFLICT-045. `05_API_Specification.md:2125` calls activation "a critical audited
command" and `08_Bank_File_and_Result_Processing.md:347` restricts it to authorized
configuration roles — and the approved permission catalogue has never contained a
permission for it. `command_catalog.yaml` already records the consequence itself, as
`permission: []` with `blocked_by_permission_gap_and_ADR_007`.

**These rows carry no `role_permissions` grants, deliberately.** Under `deny_by_default`
that means every activation request is denied, for every role, including
`business_admin`. The route, its guards, its audit record and its negative tests are all
reviewable in that state, and the day the owner approves the grant nothing else has to
change — which is the opposite of shipping the route with a borrowed permission and
discovering later that the role which drafts a configuration is the role which puts it
into production.

Borrowing `bank_profile.create_version` was the alternative and it is worse than blocking.
`permission_catalog.yaml` already marks `manager` as `approval_or_review_only` on that
permission, describing an approval authority with no permission to exercise;
`FINANCIAL_INTEGRITY_BASELINE.md` §5 makes the preparer/approver split non-configurable
elsewhere, and this is the same split.

The proposal recorded for the owner is `[manager, business_admin]` — the two the catalogue
already treats as approval authorities — and explicitly not `technical_admin`, whose
conditional role on both create permissions is `technical_validation_only`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0014"
down_revision: str | Sequence[str] | None = "20260808_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVATION_PERMISSIONS = (
    ("bank_profile.activate_version", "bank_configuration"),
    ("bank_mapping.activate", "bank_configuration"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for code, domain in ACTIVATION_PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO permissions (code, domain) VALUES (:code, :domain) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "domain": domain},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for code, _domain in ACTIVATION_PERMISSIONS:
        # Safe because nothing grants them: a `role_permissions` row would make this a
        # silent revocation rather than a clean removal.
        bind.execute(
            sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code}
        )
