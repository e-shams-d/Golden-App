"""`bank_excel_exports` matches document 04 §11.8, parsed rather than transcribed.

M7 slice 2. Same reader and same reasoning as `tests/backend/test_approval_schema.py`: a
transcription can be wrong in the same direction as the code it checks, so the document is
parsed.

**One test here is not about columns at all.** §11.8's `export_type`/`batch_approval_id` CHECK is
the constraint that keeps a preview and a final export from being confused for one another, and
`FINANCIAL_INTEGRITY_BASELINE.md` §1 forbids the confusion in as many words. Its presence is
asserted on the mapped model, where it cannot skip for want of a database — the behavioural proof
that it refuses real rows is in `tests/integration/test_export_preview.py`.

Covers: DB-EXPORT-001.
"""

from __future__ import annotations

import re

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
import pytest
from app.db.base import Base
from test_payment_request_schema import (
    expected_render,
    rendered,
    specification_columns,
)

TABLE = "bank_excel_exports"
HEADING = "## 11.8 `bank_excel_exports`"

# The repository-wide `CHAR(n)` → `VARCHAR(n)` deviation, for the same reason every other table
# records it: PostgreSQL's own documentation advises against `char(n)`, and for a value whose
# length a CHECK already fixes the two cannot behave differently.
#
# `content_hash` matters more than most here. §11.8 compares it against
# `payment_batch_versions.content_hash`, which is already `VARCHAR(64)` — a `CHAR(64)` on this
# side would compare a blank-padded value against an unpadded one.
CHAR_AS_VARCHAR: dict[str, str] = {
    "content_hash": "CHAR(64) → VARCHAR(64), and the version's side is already VARCHAR",
    "file_sha256_hash": "CHAR(64) → VARCHAR(64), the convention",
}

# §11.8 lists every column this table holds, so there are no approved additions. The dictionary
# exists anyway: the test below fails on an unexplained extra, and an empty mapping states that
# there are none rather than leaving a reader to infer it from an absent constant.
APPROVED_ADDITIONS: dict[str, str] = {}


def test_the_columns_match_document_04() -> None:
    """Both directions, and the control first.

    `specified` being empty would make every assertion below vacuous while reporting success —
    the failure shape this repository has hit more than once.
    """

    specified = specification_columns(HEADING)
    assert specified, f"{HEADING} parsed to no columns; the reader has stopped seeing the section"

    actual = set(Base.metadata.tables[TABLE].columns.keys())

    assert not (set(specified) - actual), (
        f"{TABLE} is missing columns document 04 requires: {sorted(set(specified) - actual)}"
    )
    unexplained = actual - set(specified) - set(APPROVED_ADDITIONS)
    assert not unexplained, (
        f"{TABLE} has columns no document defines: {sorted(unexplained)}"
    )


def test_every_column_has_the_type_and_nullability_document_04_states() -> None:
    """Type and nullability together.

    `batch_approval_id` is the one worth watching: §11.8 marks it `conditional`, which this
    reader takes as nullable. NOT NULL would make a preview impossible to record, and the CHECK
    is what turns "nullable" into "null exactly when this is a preview".
    """

    specified = specification_columns(HEADING)

    problems: list[str] = []
    for column, (declared, nullable) in sorted(specified.items()):
        actual_type, actual_nullable = rendered(TABLE, column)
        deviation = CHAR_AS_VARCHAR.get(column)

        if deviation is not None:
            match = re.fullmatch(r"CHAR\((\d+)\)", declared)
            assert match, (
                f"{TABLE}.{column} has a recorded CHAR→VARCHAR deviation but document 04 now "
                f"declares {declared!r}. Re-read the deviation before keeping it."
            )
            wanted = f"VARCHAR({match.group(1)})"
        else:
            wanted = expected_render(declared)

        if actual_type != wanted:
            problems.append(
                f"{TABLE}.{column}: document 04 says {declared} (expects {wanted}), "
                f"the model renders {actual_type}"
            )
        if actual_nullable != nullable:
            problems.append(
                f"{TABLE}.{column}: document 04 says "
                f"{'nullable' if nullable else 'NOT NULL'}, the model is "
                f"{'nullable' if actual_nullable else 'NOT NULL'}"
            )

    assert problems == [], "\n".join(problems)


@pytest.mark.parametrize(
    "constraint",
    [
        # §11.8's own four statements, by the names the migration gives them.
        "ck_bank_excel_exports_approval_matches_type",
        "ck_bank_excel_exports_row_count_positive",
        "ck_bank_excel_exports_total_positive",
        "uq_bank_exports_export_number",
        # The composite key §11.8 states separately, under "Composite same-version integrity".
        "fk_export_approval_same_version",
    ],
)
def test_the_constraints_document_04_states_are_on_the_model(constraint: str) -> None:
    """Structural, so it cannot skip for want of a database.

    `fk_export_approval_same_version` is the one that would be quietly lost in a refactor and the
    hardest to notice: without it a final export could cite an approval of a *different* version,
    and every other check in §11.8 would still pass — the row counts would match, the hashes
    would match, and the decision named would be somebody's real decision about something else.
    """

    names = {
        item.name
        for item in Base.metadata.tables[TABLE].constraints
        if item.name is not None
    }

    assert constraint in names, (
        f"{TABLE} has no {constraint!r}. Document 04 §11.8 states it. Present: {sorted(names)}"
    )


def test_the_active_final_export_index_excludes_previews_and_dead_finals() -> None:
    """§11.8's partial unique index, asserted by its predicate rather than by its name.

    The predicate is the whole design. Previews are outside it, so a version may be previewed as
    often as anybody likes; `voided`, `quarantined` and `generation_failed` are outside it too,
    so a voided export does not block the replacement that voided it and a failed generation does
    not block the next attempt. An index that merely existed under the right name, with
    `WHERE export_type = 'final'` and no status clause, would refuse both.
    """

    index = next(
        (
            item
            for item in Base.metadata.tables[TABLE].indexes
            if item.name == "uq_active_final_export_per_version"
        ),
        None,
    )
    assert index is not None, "the partial unique index §11.8 states is missing"
    assert index.unique, "the index exists but is not unique, so it constrains nothing"

    predicate = str(index.dialect_options["postgresql"]["where"])
    assert "export_type = 'final'" in predicate, predicate
    for still_occupying in ("generated", "validated", "downloaded", "sent_to_bank_marked"):
        assert still_occupying in predicate, f"{still_occupying} is missing from {predicate}"
    for released in ("voided", "quarantined", "generation_failed"):
        assert released not in predicate, (
            f"{released} is inside the predicate, so an export in that state would still block "
            f"its version: {predicate}"
        )
