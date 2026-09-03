"""The four batching tables match document 04, parsed rather than transcribed.

M6 slice 2. `DB-BATCH-001` says "column for column, compared by **parsing** the document's
tables rather than transcribing them", and the reason is M5 slice 1: it transcribed one type
wrong and the test passed, because a transcription can be wrong in the same direction as the
code it checks.

**Three of the four sections are markdown tables and one is a sentence.** `04_Database_Schema.md`
§11.4 gives `payment_batches` as prose — "Fields: `id`, `batch_number`, `status`, …" — with no
types and no nullability at all. A parser that looked for table rows would find none there and,
if it returned an empty mapping, would assert *nothing* about the container while reporting
success. So the prose form is parsed on purpose, its coverage is explicitly narrower than the
others', and `test_the_prose_section_is_still_prose` fails if the document gains a real table —
because on that day this file can check types for it and should.

That is the same shape as a skipped gate reading as a green gate, one level down: an empty
expectation and a satisfied expectation are indistinguishable from the exit code.

`payment_attempt_allocations` is deliberately absent. No document describes it — it is the
relation `FINANCIAL_INTEGRITY_BASELINE.md:34-49` approves without naming, recorded as G-1 — so
there is nothing to parse and a test here would be checking the code against itself. Its shape
is asserted behaviourally instead, in `tests/integration/test_batch_creation.py`.

Covers: DB-BATCH-001, DB-ATTEMPT-001.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
import pytest
from app.db.base import Base
from sqlalchemy.dialects import postgresql
from test_payment_request_schema import (
    expected_render,
    rendered,
    specification_columns,
)

SPECIFICATION = (
    Path(__file__).resolve().parents[2]
    / "Implementation Docs"
    / "02_Architecture_and_Contracts"
    / "04_Database_Schema.md"
)

POSTGRES = postgresql.dialect()

# The three sections that are real tables. `payment_batches` is handled separately below.
TABLE_SECTIONS: tuple[tuple[str, str], ...] = (
    ("payment_attempts", "## 11.3 `payment_attempts`"),
    ("payment_batch_versions", "## 11.5 `payment_batch_versions`"),
    ("payment_batch_items", "## 11.6 `payment_batch_items`"),
)

PROSE_SECTION = "## 11.4 `payment_batches`"

# The same recorded deviation M5 shipped: document 04 declares `CHAR(n)` and this repository
# stores `VARCHAR(n)`. PostgreSQL's own documentation advises against `char(n)` — it blank-pads
# to the declared width and ignores trailing spaces when comparing — and for a value whose
# length a CHECK already fixes, the two cannot behave differently.
#
# Extended rather than re-argued, because the convention is now the majority: every IBAN column
# in the tree is `VARCHAR(26)` and every digest column but one is `VARCHAR(64)`. Introducing the
# first `CHAR(26)` here would make the batch rows compare differently from the request rows they
# were copied from, which is worse than a documented deviation.
CHAR_AS_VARCHAR: dict[tuple[str, str], str] = {
    ("payment_attempts", "beneficiary_iban_snapshot"): "CHAR(26) → VARCHAR(26), the convention",
    ("payment_batch_items", "beneficiary_iban_snapshot"): "CHAR(26) → VARCHAR(26)",
    ("payment_batch_versions", "content_hash"): "CHAR(64) → VARCHAR(64)",
    ("payment_batch_items", "row_hash"): "CHAR(64) → VARCHAR(64)",
}


# Columns this repository holds that document 04 does not list, each with the approved authority
# that requires it. Keyed by `(table, column)` so an entry covers exactly one column and cannot
# spread — the same shape as `CHAR_AS_VARCHAR` above, and for the same reason: "we deviate" is a
# justification only while each deviation names what authorises it.
#
# An extra column is the more dangerous direction, because nothing else in the system would ever
# ask about it. So the test below reports one only if it is *not* listed here, and a second test
# fails if an entry here stops being an extra column — a stale exemption is a licence nobody is
# using, and it would absorb the next real extra column silently.
APPROVED_ADDITIONS: dict[tuple[str, str], str] = {
    ("payment_batch_versions", "finalized_by_admin_user_id"): (
        "DOC-CONFLICT-055 / G-11. `FINANCIAL_INTEGRITY_BASELINE.md` §5 is Resolved — Approved "
        "and requires a *recorded* finalizer actor plus a database-enforceable guard that the "
        "approver is not that actor. The word 'finalizer' appears in neither document 04 nor "
        "document 05, so §11.5 can name the preparer and §11.7 the approver and nothing can "
        "name the finalizer — and a guard cannot reference a column that does not exist. Added "
        "by 20260821_0018 on the baseline's authority, which is the same authority slice 2 "
        "created the whole of `payment_attempt_allocations` under."
    ),
}


@pytest.mark.parametrize(("table", "heading"), TABLE_SECTIONS)
def test_the_columns_match_document_04(table: str, heading: str) -> None:
    """Both directions, for the same reason M5's version gives.

    A missing column is a fact document 04 requires and the table cannot hold. An extra one is a
    fact no document defines — and that is the more dangerous of the two, because nothing else
    in the system would ever ask about it. Extras are permitted only when `APPROVED_ADDITIONS`
    names the authority.
    """

    specified = specification_columns(heading)
    actual = set(Base.metadata.tables[table].columns.keys())
    permitted = {column for (name, column) in APPROVED_ADDITIONS if name == table}

    assert not (set(specified) - actual), (
        f"{table} is missing columns document 04 requires: "
        f"{sorted(set(specified) - actual)}"
    )
    unexplained = actual - set(specified) - permitted
    assert not unexplained, (
        f"{table} has columns no document defines and no approved baseline authorises: "
        f"{sorted(unexplained)}. Add an APPROVED_ADDITIONS entry naming the authority, or "
        "remove the column."
    )


def test_every_approved_addition_is_still_an_addition() -> None:
    """An exemption for a column document 04 now lists is a licence nobody is using.

    The same shape as the status-drift gate's `test_every_approved_omission_is_still_an_omission`:
    on the day G-11 is settled and §11.5 gains the column, this fails and asks for the entry to
    go — otherwise the exemption sits there and absorbs the next genuinely undocumented column
    without anybody noticing.
    """

    stale: list[str] = []
    for (table, column), reason in sorted(APPROVED_ADDITIONS.items()):
        heading = next(
            (head for name, head in TABLE_SECTIONS if name == table), None
        )
        assert heading is not None, f"{table} has an addition but no parsed section"
        if column in specification_columns(heading):
            stale.append(f"{table}.{column} is now in document 04; drop its entry ({reason[:60]}…)")

    assert stale == [], "\n".join(stale)


@pytest.mark.parametrize(("table", "heading"), TABLE_SECTIONS)
def test_every_column_has_the_type_and_nullability_document_04_states(
    table: str, heading: str
) -> None:
    """Type and nullability together, because either alone is half the claim.

    Nullability is not the lesser half. `beneficiary_name_snapshot` being NOT NULL is what makes
    an item answer "who was paid" from its own row; nullable, it would be a column that is
    usually filled, and a bank file with a blank payee name is a row somebody has to explain by
    hand.
    """

    specified = specification_columns(heading)

    problems: list[str] = []
    for column, (declared, nullable) in sorted(specified.items()):
        actual_type, actual_nullable = rendered(table, column)
        deviation = CHAR_AS_VARCHAR.get((table, column))

        if deviation is not None:
            match = re.fullmatch(r"CHAR\((\d+)\)", declared)
            assert match, (
                f"{table}.{column} has a recorded CHAR→VARCHAR deviation but document 04 now "
                f"declares {declared!r}. Re-read the deviation before keeping it."
            )
            wanted = f"VARCHAR({match.group(1)})"
        else:
            wanted = expected_render(declared)

        if actual_type != wanted:
            problems.append(
                f"{table}.{column}: document 04 says {declared} (expects {wanted}), "
                f"the model renders {actual_type}"
            )
        if actual_nullable != nullable:
            problems.append(
                f"{table}.{column}: document 04 says "
                f"{'nullable' if nullable else 'NOT NULL'}, the model is "
                f"{'nullable' if actual_nullable else 'NOT NULL'}"
            )

    assert problems == [], "\n".join(problems)


def _prose_fields() -> set[str]:
    """The backticked names in §11.4's `Fields:` sentence.

    `timestamps` is expanded: the sentence ends "…`record_version`, timestamps", which is
    document 04's shorthand for the pair every mutable table carries (`:106-223` sets that
    convention). Expanded here rather than excluded, because excluding it would stop this test
    checking that the container has them at all.
    """

    text = SPECIFICATION.read_text(encoding="utf-8")
    start = text.index(PROSE_SECTION)
    section = text[start : text.index("\n## ", start + len(PROSE_SECTION))]

    line = next(
        (candidate for candidate in section.splitlines() if candidate.startswith("Fields:")),
        None,
    )
    assert line is not None, (
        f"{PROSE_SECTION} no longer has a `Fields:` sentence. If it gained a column table, "
        "parse it with the others and delete this function."
    )

    fields = set(re.findall(r"`([a-z_]+)`", line))
    assert "timestamps" not in fields, "the shorthand is unbackticked prose, not a field"
    assert line.rstrip().endswith("timestamps."), (
        "§11.4 no longer ends with the `timestamps` shorthand; read what replaced it before "
        "assuming the pair is still implied"
    )
    return fields | {"created_at", "updated_at"}


def test_the_container_holds_exactly_the_fields_the_prose_names() -> None:
    """`payment_batches`, checked against a sentence rather than a table.

    Names only. §11.4 gives no types and no nullability, so this is the whole of what the
    document supports — and saying so is the point: the coverage here is narrower than for the
    other three, and a reader should be able to see that from the test rather than infer it from
    a passing run.
    """

    specified = _prose_fields()
    actual = set(Base.metadata.tables["payment_batches"].columns.keys())

    assert actual == specified, (
        "payment_batches does not match §11.4's field list.\n"
        f"  missing: {sorted(specified - actual)}\n"
        f"  extra:   {sorted(actual - specified)}"
    )


def test_the_prose_section_is_still_prose() -> None:
    """Fails on the day §11.4 gains a real column table, which is when this file can do more.

    Without this, the document could grow types and nullability for the container and the test
    above would go on checking names only — passing, and quietly under-checking the one table
    whose status column is a projection nine of eleven states derive.
    """

    text = SPECIFICATION.read_text(encoding="utf-8")
    start = text.index(PROSE_SECTION)
    section = text[start : text.index("\n## ", start + len(PROSE_SECTION))]

    assert "| Column | Type |" not in section, (
        f"{PROSE_SECTION} now has a column table. Move `payment_batches` into TABLE_SECTIONS "
        "and delete the two prose tests: the document can now say more than names."
    )


# `:849-859` requires the lineage columns so a retry can be attributed later. M6 writes none of
# them, and the obligation is that they are nullable and unwritten rather than absent.
LINEAGE_COLUMNS: tuple[str, ...] = (
    "retry_of_attempt_id",
    "supersedes_attempt_id",
    "bank_tracking_number",
    "bank_result_at",
    "failure_code",
    "failure_reason",
    "confirmed_by_admin_user_id",
    "confirmed_at",
)

# **Lineage columns a later milestone legitimately writes, and the one place each is written.**
#
# `DB-ATTEMPT-001` said M6 writes none of these. M9 slice 3B writes one: §17.5's retry creates a
# new attempt carrying `retry_of_attempt_id`, which is the whole point of the column existing.
#
# Removing it from `LINEAGE_COLUMNS` would have been the easy edit and would have lost two
# guarantees — that the column is still nullable, and that nothing *else* writes it. So the
# column stays in the list above, comes out of the prohibition scan, and gains its own assertion
# below: written by this module and by no other.
WRITTEN_BY_EXACTLY_ONE_COMMAND: dict[str, str] = {
    "retry_of_attempt_id": "commands/payment_retry.py",
}

# **Modules that write one of these names onto a different table entirely.**
#
# The scan's docstring below already records that `confirmed_at` and `confirmed_by_admin_user_id`
# are not unique to `payment_attempts` — `confirmed_evidence_links` carries them too — and that the
# AST walk fixed the *constructor* half of that collision. It did not fix the other half: an
# attribute write like `receipt.confirmed_at = now` is indistinguishable from
# `attempt.confirmed_at = now` without type inference the scan deliberately does not attempt.
#
# M10 slice 6 is the first module to hit it. `incoming_confirmation.py` confirms an incoming
# payment: it writes both names on `incoming_payment_receipts` and `incoming_payment_matches`, and
# `04_Database_Schema.md` §10.3 and §10.7 name those columns on both tables.
#
# **The exemption is per module and per column, and it checks itself.** A module listed here that
# can reach `PaymentAttempt` fails `test_an_exempt_module_cannot_reach_payment_attempts` below, so
# this is not a promise that the module writes another table — it is a proof that it cannot write
# this one.
WRITES_ANOTHER_TABLES_COLUMN: dict[str, tuple[str, ...]] = {
    # M10 slice 8. `gold_dispatches.confirmed_at` is the *trader* acknowledging that gold arrived
    # — document 06 §12.3 — and has nothing to do with a payment attempt. The second module to need
    # this exemption, and the guard below is what keeps a second one from becoming a habit: it
    # imports no PaymentAttempt, so it cannot reach the table the scan protects.
    "commands/gold_sale_closure.py": ("confirmed_at",),
    "commands/incoming_confirmation.py": (
        "confirmed_at",
        "confirmed_by_admin_user_id",
    ),
}


def test_every_lineage_column_exists_and_is_nullable() -> None:
    """`DB-ATTEMPT-001`, the half that is a property of the schema.

    Nullable **and** present. Present because a retry in M8 must be able to say what it retries,
    and a column added later cannot be backfilled for attempts that already failed. Nullable
    because M6 knows none of these facts, and NOT NULL would force this milestone to invent a
    value — which is exactly the placeholder `FINANCIAL_INTEGRITY_BASELINE.md:22-23` forbids.
    """

    columns = Base.metadata.tables["payment_attempts"].columns
    for name in LINEAGE_COLUMNS:
        assert name in columns, f"payment_attempts has no {name}; `:849-859` requires it"
        assert columns[name].nullable, (
            f"payment_attempts.{name} is NOT NULL, so this milestone would have to invent a "
            "value for a fact only a bank can supply"
        )


def test_nothing_in_the_application_writes_a_lineage_column() -> None:
    """`DB-ATTEMPT-001`, the half that is a property of the code.

    The columns above exist for M7 and M8. Asserted by scanning the application source rather
    than by observing a created attempt, because "the one path I tested did not write it" is a
    much weaker claim than "no path can".

    A future milestone that legitimately writes one of these will fail here, which is the
    intent: widening the set is a decision, and it should be made by editing this list.

    **Two of the eight names are not unique to `payment_attempts`, which the first version of
    this scan did not allow for.** `confirmed_by_admin_user_id` and `confirmed_at` are also
    §12.6 columns on `confirmed_evidence_links`, so M9 slice 2 writing its *own* table tripped a
    check about a different table entirely. A textual scan for a bare name cannot tell those
    apart.

    So the walk is an AST one and asks what is being written rather than which words appear:

    - `something.confirmed_at = ...` — an attribute write, conservative about the object,
      because an instance's class is not decidable here and `attempt.confirmed_at` is exactly
      the shape this test exists to catch;
    - `PaymentAttempt(confirmed_at=...)` — a keyword argument **to that constructor only**.

    A keyword argument to any other call is not a write to this table. That removes the false
    positive without an exclusion list, which is the same move M8 made three times when prose
    collided with a grep.
    """

    application = Path(__file__).resolve().parents[2] / "services" / "backend" / "app"
    lineage = set(LINEAGE_COLUMNS) - set(WRITTEN_BY_EXACTLY_ONE_COMMAND)
    offenders: list[str] = []

    for source in sorted(application.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        where = source.relative_to(application)

        for node in ast.walk(tree):
            exempt = WRITES_ANOTHER_TABLES_COLUMN.get(where.as_posix(), ())
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr in lineage
                        and target.attr not in exempt
                    ):
                        offenders.append(f"{where} assigns {target.attr}")
            elif isinstance(node, ast.Call):
                callee = node.func
                callee_name = (
                    callee.attr
                    if isinstance(callee, ast.Attribute)
                    else getattr(callee, "id", None)
                )
                if callee_name != "PaymentAttempt":
                    continue
                for keyword in node.keywords:
                    if keyword.arg in lineage:
                        offenders.append(f"{where} constructs an attempt with {keyword.arg}")

    assert sorted(set(offenders)) == [], (
        "a lineage column is written somewhere in the application, and `DB-ATTEMPT-001` claims "
        "none is:\n" + "\n".join(f"  {offender}" for offender in sorted(set(offenders)))
    )


def test_each_exempted_lineage_column_is_written_in_exactly_one_place() -> None:
    """The other half of the exemption, and what makes it narrower than a deletion.

    `retry_of_attempt_id` came out of the prohibition scan because M9 slice 3B writes it. This
    asserts it is written *there* and nowhere else — so a second writer appearing anywhere in the
    application fails here rather than inheriting the exemption.
    """

    application = Path(__file__).resolve().parents[2] / "services" / "backend" / "app"

    for column, expected in WRITTEN_BY_EXACTLY_ONE_COMMAND.items():
        writers: set[str] = set()
        for source in sorted(application.rglob("*.py")):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            where = str(source.relative_to(application)).replace("\\", "/")
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Attribute) and target.attr == column:
                            writers.add(where)
                elif isinstance(node, ast.Call):
                    callee = node.func
                    callee_name = (
                        callee.attr
                        if isinstance(callee, ast.Attribute)
                        else getattr(callee, "id", None)
                    )
                    if callee_name != "PaymentAttempt":
                        continue
                    if any(keyword.arg == column for keyword in node.keywords):
                        writers.add(where)

        assert writers == {expected}, (
            f"{column} is written by {sorted(writers)} and the exemption names only {expected}. "
            "Either the writer moved, or a second one appeared and must be a decision rather "
            "than an inheritance."
        )


def test_the_lineage_scan_catches_both_shapes_and_ignores_the_third(tmp_path: Path) -> None:
    """Guard the guard, on the two shapes it looks for and the two it must ignore.

    Without this the AST walk could quietly match nothing — the failure mode that made the
    textual version worth replacing is the one that would make its replacement useless, and a
    scan reporting a clean application is indistinguishable from a scan looking for the wrong
    node type.
    """

    planted = tmp_path / "writer.py"
    planted.write_text(
        "def f(attempt, now, who):\n"
        "    attempt.confirmed_at = now\n"
        "    PaymentAttempt(confirmed_by_admin_user_id=who)\n"
        "    ConfirmedEvidenceLink(confirmed_at=now)\n"
        "    return {'confirmed_at': now}\n",
        encoding="utf-8",
    )

    lineage = set(LINEAGE_COLUMNS)
    found: list[str] = []
    for node in ast.walk(ast.parse(planted.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in lineage:
                    found.append(f"attribute:{target.attr}")
        elif isinstance(node, ast.Call):
            callee = node.func
            callee_name = (
                callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", None)
            )
            if callee_name != "PaymentAttempt":
                continue
            for keyword in node.keywords:
                if keyword.arg in lineage:
                    found.append(f"constructor:{keyword.arg}")

    assert sorted(found) == [
        "attribute:confirmed_at",
        "constructor:confirmed_by_admin_user_id",
    ], (
        f"the walk found {sorted(found)}. It must catch the attribute write and the "
        "PaymentAttempt keyword, and must not catch the same keyword on another constructor or "
        "a dictionary key."
    )


def test_an_exempt_module_cannot_reach_payment_attempts() -> None:
    """Guard the exemption above, so it cannot become the hole it looks like.

    `WRITES_ANOTHER_TABLES_COLUMN` takes a module's word that its `confirmed_at` belongs to a
    different table. That word is worth nothing on its own — the next slice could add one line to
    the same module and write the attempt's column with the scan looking away.

    So the exemption is checked rather than trusted: an exempt module must not import
    `PaymentAttempt` at all. Enforcement by absence, which is what this repository reaches for
    whenever a rule would otherwise be a promise. A module that genuinely needs both would have to
    be split, and that is the right outcome — confirming an incoming payment and confirming an
    outgoing attempt are different acts on different money.
    """

    application = Path(__file__).resolve().parents[2] / "services" / "backend" / "app"

    assert WRITES_ANOTHER_TABLES_COLUMN, (
        "the exemption map is empty, so this guard asserts nothing. A gate whose input is empty "
        "passes."
    )

    for module, columns in WRITES_ANOTHER_TABLES_COLUMN.items():
        source = application / module
        assert source.exists(), f"{module} is exempted and does not exist"
        assert columns, f"{module} is exempted for no column"

        tree = ast.parse(source.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom | ast.Import):
                imported.update(alias.name for alias in node.names)

        assert "PaymentAttempt" not in imported, (
            f"{module} is exempted from the lineage scan and imports PaymentAttempt. The "
            "exemption exists because the module writes another table's identically named "
            "column; if it can reach an attempt, the scan is looking away from exactly what it "
            "was written to catch."
        )
        assert not any(name.endswith("payment_attempt") for name in imported), (
            f"{module} is exempted and imports the payment attempt module"
        )
