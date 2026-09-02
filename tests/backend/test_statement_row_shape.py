"""What `bank_statement_rows` must carry, and what it must never carry.

M10 slice 4. `04_Database_Schema.md` §10.6 and `08_Bank_File_and_Result_Processing.md` §8.4-8.5.

**The forbidden columns are the point.** §10.6 `:796` refuses three of them in two sentences: "Do
not store generic `matched_entity_type/id` or a mutable `is_matched` flag as the source of truth.
Match state is derived from dedicated match records." Nothing behavioural can catch their arrival —
adding `is_matched` to the model breaks no test, and slice 5 could then write it in good faith,
producing a second mutable answer to a question the match rows already answer. So the assertion is
over the mapped columns, and it fails the moment one appears.

**Read from `Base.metadata`, not from the migration's source.** A substring scan for
`is_matched` over the revision file is defeated by the prose that justifies it — this repository
has watched that happen nine times, most recently in M9 slice 7. The metadata is what autogenerate
compares against and `test_schema_matches_models.py` already holds the database to it.

Covers: DB-ROW-001.
"""

from __future__ import annotations

from app.db.base import Base
from app.db.models.bank_statement import ROW_STATUSES, BankStatementRow

# §10.6 `:796`, verbatim in identifiers. Two spellings of the polymorphic pair are listed because
# document 04 writes it as `matched_entity_type/id` and either expansion is the thing it refuses.
FORBIDDEN_COLUMNS = frozenset(
    {
        "matched_entity_type",
        "matched_entity_id",
        "is_matched",
    }
)

# §10.6's own field list, plus `document_number` from document 08 §8.4 — added because §8.7's
# duplicate signals include "same tracking/document number" and the schema list omits it.
REQUIRED_COLUMNS = frozenset(
    {
        "id",
        "bank_statement_import_run_id",
        "row_number",
        "transaction_at_normalized",
        "transaction_date_raw",
        "transaction_time_raw",
        "amount_in_irr",
        "amount_out_irr",
        "balance_irr",
        "document_number",
        "tracking_number",
        "description",
        "counterparty_name",
        "counterparty_account",
        "counterparty_iban",
        "raw_data",
        "row_fingerprint",
        "status",
        "created_at",
    }
)


def _columns() -> frozenset[str]:
    table = Base.metadata.tables["bank_statement_rows"]
    return frozenset(column.name for column in table.columns)


def test_no_polymorphic_match_column_exists() -> None:
    """`DB-ROW-001`, asserted as an absence.

    The failure this guards is not a bug somebody writes today. It is a column somebody adds in
    slice 5 because a join felt slow, after which two records disagree about whether a row is
    matched and the mutable one wins because it is easier to read.
    """

    present = sorted(FORBIDDEN_COLUMNS & _columns())
    assert present == [], (
        f"bank_statement_rows carries {present}. `04_Database_Schema.md:796` refuses all three: "
        '"Match state is derived from dedicated match records." Slice 5 builds those records; a '
        "flag here would be a second, mutable answer to the same question."
    )


def test_every_column_document_04_names_is_present() -> None:
    """`DB-ROW-001`, the other direction.

    A table missing `transaction_date_raw` still parses statements and still passes every
    behavioural test — right up to the first mapping correction, when the raw string that would
    have let the row be re-normalised turns out never to have been stored.
    """

    missing = sorted(REQUIRED_COLUMNS - _columns())
    assert missing == [], (
        f"bank_statement_rows is missing {missing}, which §10.6 and document 08 §8.4 name."
    )


def test_raw_and_normalized_are_both_present_for_the_date() -> None:
    """`SVC-ROW-001`. §18 `:1229`: "raw and normalized values are retained".

    Named separately from the column list above because it is the one pair whose loss is invisible
    until it matters. Document 08 §8.5 states the rule three times — preserve every raw source
    value, preserve raw Jalali/Gregorian strings, normalize without losing originals — and §8.9
    requires a reparse after a mapping correction, which is exactly when the raw string is the only
    thing that can be re-read.
    """

    columns = _columns()
    for raw, normalized in (
        ("transaction_date_raw", "transaction_at_normalized"),
        ("transaction_time_raw", "transaction_at_normalized"),
    ):
        assert raw in columns and normalized in columns, (
            f"{raw} and {normalized} must both exist; keeping only the normalized value makes a "
            "mapping correction unreplayable"
        )

    table = Base.metadata.tables["bank_statement_rows"]
    raw = table.columns["raw_data"]
    assert raw.nullable is False, (
        "raw_data is nullable, so a row may exist with no copy of what the bank wrote. §8.5's "
        "first rule is 'Preserve every raw source value'."
    )
    # **And no server default**, which is the same property from the other side. The first version
    # of `20260907_0038` gave the column `'{}'::jsonb`, and `test_schema_matches_models.py` caught
    # it because the model declared none. A default would let an INSERT that forgot the raw copy
    # succeed and look complete — NOT NULL alone does not refuse that, it only refuses an explicit
    # null.
    assert raw.server_default is None, (
        "raw_data has a server default, so a row can be written with no raw copy and still "
        "satisfy NOT NULL. An empty raw copy is indistinguishable from a statement line nobody "
        "preserved."
    )


def test_the_row_is_not_shaped_like_something_editable() -> None:
    """§10.6: "Immutable rows tied to one import run."

    No `record_version` and no `updated_at`. Both describe a row somebody edits, and their presence
    would be an invitation the migration's withheld UPDATE grant then has to refuse — a schema
    saying two different things about the same table.
    """

    columns = _columns()
    for column in ("record_version", "updated_at"):
        assert column not in columns, (
            f"bank_statement_rows carries {column!r}, which describes a row somebody edits. §10.6 "
            "calls these rows immutable and `20260907_0038` grants no UPDATE on any column."
        )


def test_the_status_check_carries_document_08s_five_states() -> None:
    """§8.6's five, and no others.

    `status_catalog.yaml` has no `bank_statement_row` aggregate — the only M10 table for which that
    is true — so document 08 is the sole source and `test_status_catalogue_drift.py` carries this
    column as a `LOCAL_LIFECYCLES` entry. That makes this the only place the value set is held to
    the document, which is why it is asserted exactly rather than as a subset.
    """

    assert set(ROW_STATUSES) == {
        "valid",
        "warning",
        "invalid",
        "ignored_empty",
        "possible_duplicate",
    }
    assert BankStatementRow.__tablename__ == "bank_statement_rows"
