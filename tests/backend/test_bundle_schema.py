"""The three bundle tables carry what §12.1-12.3 specifies, and refuse what it forbids.

M8 slice 1. `DB-BUNDLE-001` in two halves: the field lists here, against the models, and the
constraints against a live PostgreSQL in `tests/integration/test_bundle_schema_privileges.py` —
because a CHECK that exists in a model and not in the migrated database is exactly the drift the
integration gate is for.

**The field lists are parsed from document 04, not transcribed.** M5 shipped a wrong type behind a
green test because a hand-copied list agreed with the code that copied it, and §12.1's fields are
given as one prose sentence that is easy to read past.

Covers: DB-BUNDLE-001, SVC-BUNDLE-002.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = (
    REPOSITORY_ROOT
    / "Implementation Docs"
    / "02_Architecture_and_Contracts"
    / "04_Database_Schema.md"
)

_FIELD = re.compile(r"`([a-z_]+)`")


def documented_fields(heading: str) -> set[str]:
    """The field names in the `Fields: ...` sentence under a heading.

    §12.1 and §12.2 give their columns as one backticked prose list rather than a table, which is
    why this parses backticks rather than rows. `timestamps` and `nullable` appear in the same
    sentence and are not columns; they are filtered by the caller's expectation, not here, so a
    document edit that turned one into a column would show up as a difference rather than be eaten.
    """

    text = SCHEMA.read_text(encoding="utf-8")
    start = text.index(heading)
    body = text[start + len(heading) :]
    sentence = body[: body.index("\n\n", body.index("Fields:"))]
    return set(_FIELD.findall(sentence[sentence.index("Fields:") :]))


def documented_table_columns(heading: str) -> set[str]:
    """The first column of every row of the markdown table under a heading. §12.4's shape."""

    text = SCHEMA.read_text(encoding="utf-8")
    start = text.index(heading)
    body = text[start + len(heading) :]
    block = body[: body.index("\n```")]
    found: set[str] = set()
    for line in block.splitlines():
        if not line.startswith("| `"):
            continue
        found.add(line.split("`")[1])
    return found


def model_columns(name: str) -> set[str]:
    from app.db.models import bank_result_bundle as models

    return {column.name for column in getattr(models, name).__table__.columns}


def test_the_document_still_lists_these_tables() -> None:
    """The control. A parser returning an empty set would make every comparison below vacuous."""

    assert len(documented_fields("## 12.1 `bank_result_bundles`")) > 10
    assert len(documented_fields("## 12.2 `bank_result_bundle_files`")) == 7
    assert len(documented_fields("## 12.3 `bank_result_bundle_batch_links`")) > 7


def test_the_bundle_carries_every_documented_field() -> None:
    """`DB-BUNDLE-001`. §12.1's list, minus the two words that are not columns.

    `timestamps` is document 04's shorthand for `created_at`/`updated_at` throughout, and
    `nullable` appears inside the sentence as an annotation on `bank_profile_id`. Both are named
    here rather than filtered by a regex, so a genuine new column cannot hide behind the filter.
    """

    documented = documented_fields("## 12.1 `bank_result_bundles`") - {"timestamps", "nullable"}
    missing = sorted(documented - model_columns("BankResultBundle"))

    assert missing == [], f"§12.1 names these and the model has none of them: {missing}"


def test_the_bundle_file_carries_every_documented_field() -> None:
    """`DB-BUNDLE-001` for §12.2, whose seven fields are given exactly."""

    documented = documented_fields("## 12.2 `bank_result_bundle_files`")
    missing = sorted(documented - model_columns("BankResultBundleFile"))

    assert missing == [], f"§12.2 names these and the model has none of them: {missing}"


def test_the_batch_link_carries_every_documented_field() -> None:
    """`DB-BUNDLE-001` for §12.3."""

    documented = documented_fields("## 12.3 `bank_result_bundle_batch_links`") - {
        "nullable",
        "timestamps",
    }
    missing = sorted(documented - model_columns("BankResultBundleBatchLink"))

    assert missing == [], f"§12.3 names these and the model has none of them: {missing}"


def test_the_link_table_carries_nothing_that_could_be_read_as_proof_of_payment() -> None:
    """`SVC-BUNDLE-001`'s structural half, and the most valuable assertion in this file.

    §12.3 at `:1199`: "This association does not prove payment completion. Attempt/segment
    confirmation remains authoritative." A comment saying so is worth nothing if the table has a
    column that means otherwise — the first reader to find `confirmed_at` on a link will treat it
    as confirmation, and they will be reading the schema rather than the prose.

    Listed as forbidden names rather than as an allow-list, because the allow-list is already
    asserted above: this says *what must never appear*, which is the claim that survives somebody
    adding a column for a good-sounding reason.
    """

    columns = model_columns("BankResultBundleBatchLink")

    forbidden = {
        "confirmed_at",
        "confirmed_by_admin_user_id",
        "payment_attempt_id",
        "receipt_segment_id",
        "amount_irr",
        "paid_at",
        "is_paid",
        "settlement_status",
    }
    present = sorted(forbidden & columns)

    assert present == [], (
        f"these columns would make a batch link readable as proof of payment: {present}. "
        "§12.3 says the association proves nothing; attempt and segment confirmation is "
        "authoritative and belongs to M9."
    )


@pytest.mark.parametrize(
    ("constant", "expected"),
    [
        ("FILE_ROLES", {"source", "normalized", "preview", "structured_result"}),
        ("BUNDLE_STATUSES", None),
    ],
)
def test_the_vocabularies_match_their_authority(constant: str, expected: set[str] | None) -> None:
    """`SVC-BUNDLE-002` for the roles, and the catalogue for the statuses.

    §12.2 at `:1191` gives the four roles in one line. The statuses come from
    `status_catalog.yaml` rather than from document 04, which names none — and
    `test_status_catalogue_drift.py` is what holds the CHECK to the aggregate; this asserts the
    Python constant agrees with the same source, so the two cannot drift apart between them.
    """

    from app.db.models import bank_result_bundle as models

    values = set(getattr(models, constant))

    if expected is not None:
        assert values == expected
        return

    import yaml

    catalogue = yaml.safe_load(
        (REPOSITORY_ROOT / "docs" / "governance" / "status_catalog.yaml").read_text(
            encoding="utf-8"
        )
    )
    aggregates = catalogue.get("aggregates", catalogue)
    canonical = {
        state["canonical"] for state in aggregates["bank_result_bundle"]["states"]
    }

    assert values == canonical


def test_the_counts_cannot_disagree_with_each_other() -> None:
    """The CHECK that document 04 does not state, and the reason it is here.

    §12.1 at `:1179` says the three counts are one fact counted three ways — "recomputed/validated
    transactionally from segments/tasks" and "not independent financial truth". Three independent
    integers with three independent `>= 0` CHECKs are exactly what that sentence warns against, so
    the model adds a fourth constraint holding the parts to the whole.

    Asserted on the model's constraint list rather than by inserting a bad row, which is the
    integration test's job: this is the claim that the constraint *exists*, and it is the one that
    would silently disappear in a refactor.
    """

    from app.db.models.bank_result_bundle import BankResultBundle

    texts = [
        str(constraint.sqltext)
        for constraint in BankResultBundle.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    ]
    reconciling = [
        text for text in texts if "resolved_segment_count" in text and "segment_count" in text
    ]

    assert any("+" in text for text in reconciling), (
        "no CHECK holds resolved + unresolved to segment_count, so the three cached counts can "
        "disagree with each other"
    )


def test_a_closed_bundle_must_say_who_closed_it() -> None:
    """The separation CHECK, and it is a CHECK because a CHECK cannot be forgotten.

    §12.1 gives `closed_at` and `closed_by_admin_user_id` and does not say they travel with the
    status. M7 slice 1 established the shape for `batch_approvals`: a CHECK on one row, stating
    that a terminal status has its terminal facts and that nothing else has them. Without the
    second half a bundle could carry a closer while still open, which reads as closed to anything
    that checks the timestamp rather than the status.
    """

    from app.db.models.bank_result_bundle import BankResultBundle

    texts = [
        str(constraint.sqltext)
        for constraint in BankResultBundle.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    ]
    closing = [text for text in texts if "closed_at" in text]

    assert closing, "nothing ties closed_at to the closed status"
    assert any("IS NULL" in text and "IS NOT NULL" in text for text in closing), (
        "the closing CHECK only covers one direction, so a bundle can carry a closer while open"
    )
