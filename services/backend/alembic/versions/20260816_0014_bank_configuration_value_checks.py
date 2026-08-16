"""Value CHECKs for bank configuration status and mapping type.

DOC-CONFLICT-047. `bank_mappings.file_type` means the **mapping type** in document 04 —
"statement import, outgoing export, result import" — and the **file format** in document
08, where it is `xlsx | csv | fixed_width | json`. The same column name, two meanings,
both plausible on sight.

M2 implemented document 04's reading, visibly: both mapping uniques include this column so
an import mapping and an export mapping can coexist at `template_version` 1, which is only
coherent under that reading. An implementer arriving from document 08 would write `xlsx`
here, the uniques would then permit two statement-import mappings at one version, and the
failure would surface during the first bank export in M7 — three milestones from the write
that caused it.

This CHECK moves that failure to the write. It is not canonicalisation of a status
catalogue entry: `status_catalog.yaml` records `bank_mapping` with `canonical: null`, and
what is constrained here is the *type* column, which no catalogue entry covers.

**No status CHECK is added, and that was a correction.** This migration first constrained
`bank_profile_versions.status` and `bank_mappings.status` to `[draft, active, retired]`,
on the reasoning that the catalogue lists exactly those three so constraining to them
decides nothing. `test_status_catalogue_drift.py` refused it, and its own note says why the
rule is written down at all: so "the next person to reach for an enum finds the reason
before the constraint". The reasoning above is precisely how an alias set quietly becomes
canonical, which is what `canonical: null` reserves for a decision nobody has made.

`file_type` is a different act. It is a *type* column, no catalogue entry covers it, and
what it refuses is a value from another document's vocabulary rather than a spelling of
this one's.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260816_0014"
down_revision: str | Sequence[str] | None = "20260808_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MAPPING_TYPES = ("statement_import", "payment_export", "payment_result_import")


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_check_constraint(
        "ck_bank_mappings_file_type",
        "bank_mappings",
        f"file_type IN ({_quoted(MAPPING_TYPES)})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_bank_mappings_file_type", "bank_mappings", type_="check")
