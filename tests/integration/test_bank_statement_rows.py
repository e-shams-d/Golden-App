"""Parsing a real statement, and the rows it produces. M10 slice 4.

Against a real PostgreSQL and a real `.xlsx`. `04_Database_Schema.md` §10.6,
`08_Bank_File_and_Result_Processing.md` §8.4-8.6 and §22.2.

**The workbook is built here rather than committed.** A binary fixture would have to be trusted:
nobody reviewing this file could tell what is in it, and the first thing a reader wants to know
about a parser test is exactly which cells it was given. `openpyxl` writes it in six lines and the
test says what every row means.

**Two properties carry the slice.** Rows are written for *every* source line, including the ones
that could not be read — §22.2's "never partially hide invalid rows" — and the raw values survive
beside the normalized ones, which is what makes a reparse after a mapping correction worth doing.

Covers: DB-ROW-001, SVC-ROW-001.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities
from openpyxl import Workbook

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "X-CSRF-Token"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"

# The mapping every test parses with: the headers a bank writes, mapped to the parser's canonical
# field names. Persian headers on purpose — this platform's banks do not write English ones, and a
# parser that only matched ASCII would pass every test here and fail on the first real file.
STATEMENT_MAPPING: dict[str, Any] = {
    "columns": [
        {"header": "تاریخ", "field": "transaction_date"},
        {"header": "ساعت", "field": "transaction_time"},
        {"header": "بستانکار", "field": "amount_in_irr"},
        {"header": "بدهکار", "field": "amount_out_irr"},
        {"header": "مانده", "field": "balance_irr"},
        {"header": "شناسه پیگیری", "field": "tracking_number"},
        {"header": "شرح", "field": "description"},
        {"header": "واریزکننده", "field": "counterparty_name"},
    ]
}

HEADERS = [
    "تاریخ",
    "ساعت",
    "بستانکار",
    "بدهکار",
    "مانده",
    "شناسه پیگیری",
    "شرح",
    "واریزکننده",
    # Deliberately unmapped. §22.2 refuses to hide anything, and an unmapped column is usually the
    # first sign a bank changed its format — so it must reach `raw_data` and `unmapped_headers`.
    "شعبه",
]

# Five rows, each chosen for one thing the parser must do.
STATEMENT_ROWS: list[list[Any]] = [
    # 1. Ordinary and complete: an ISO date, a time, an incoming amount.
    ["2026-08-11", "09:15:23", "2000000000", "", "12300000000", "TRK-1001", "واریز", "احمدی", "۱۲"],
    # 2. Persian digits throughout. `normalization_rules` folds them; the raw copy must not be
    #    folded, because §8.5's first rule is to preserve every raw source value.
    [
        "2026-08-12", "10:00:00", "۳۰۰۰۰۰۰۰۰۰", "", "۱۵۳۰۰۰۰۰۰۰۰۰",
        "TRK-1002", "واریز", "رضایی", "۱۲",
    ],
    # 3. A Jalali date. Preserved raw and left unconverted — ADR-006 has not chosen the calendar
    #    conversion, so the row is a `warning` with an instant of null rather than a guess.
    ["1405/05/22", "11:30:00", "500000000", "", "15800000000", "TRK-1003", "واریز", "کریمی", "۹"],
    # 4. An outgoing amount, which must never be read as incoming. §8.5: "Do not silently convert
    #    debit to credit or vice versa."
    ["2026-08-13", "12:00:00", "", "750000000", "15050000000", "TRK-1004", "برداشت", "", "۹"],
    # 5. An amount that is not a whole number of rial. §8.5 rejects fractional IRR; the row is kept
    #    and flagged rather than dropped, and its amount stays null rather than being rounded.
    ["2026-08-14", "13:00:00", "1000.5", "", "15051000500", "TRK-1005", "واریز", "نوری", "۹"],
]


@pytest.fixture(scope="module")
def migrated(module_provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        module_provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=module_provisioned_database.app_role,
        worker_role=module_provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return module_provisioned_database


def _workbook_bytes(rows: list[list[Any]], headers: list[str] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers if headers is not None else HEADERS)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def world(migrated: RuntimeIdentities, tmp_path_factory: Any) -> Iterator[dict[str, Any]]:
    from app.core.config import Settings
    from app.core.runtime import RuntimeServices
    from app.main import create_app
    from app.security.passwords import Argon2Parameters, hash_password
    from fastapi.testclient import TestClient

    storage_root = tmp_path_factory.mktemp("rows-storage")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=storage_root,
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="t" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {
        name: uuid.uuid4()
        for name in ("bank", "version", "account", "mapping", "broken_mapping")
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'rowbank', 'Row Bank', 'active')",
            (ids["bank"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "config_hash) VALUES (%s, %s, 1, 'active', %s)",
            (ids["version"], ids["bank"], hashlib.sha256(b"version").hexdigest()),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, account_role, status) "
            "VALUES (%s, %s, 'Incoming', 'incoming_destination', 'active')",
            (ids["account"], ids["bank"]),
        )
        import json

        for key, mapping, template in (
            ("mapping", STATEMENT_MAPPING, 1),
            # A mapping that names a column the file does not have. §22.2's failure path: the run
            # fails, the file is preserved, and a corrected mapping may be run against it.
            (
                "broken_mapping",
                {
                    "columns": [
                        {"header": "تاریخ", "field": "transaction_date"},
                        {"header": "مبلغ واریزی", "field": "amount_in_irr"},
                    ]
                },
                2,
            ),
        ):
            connection.execute(
                "INSERT INTO bank_mappings (id, bank_profile_version_id, file_type, "
                "template_version, status, mapping, normalization_rules, config_hash) "
                "VALUES (%s, %s, 'statement_import', %s, 'active', %s, %s, %s)",
                (
                    ids[key],
                    ids["version"],
                    template,
                    json.dumps(mapping),
                    json.dumps({"digits": "fold_persian_to_ascii"}),
                    hashlib.sha256(key.encode()).hexdigest(),
                ),
            )
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES ('rows_accountant', 'Accountant', %s, 'active')",
            (encoded,),
        )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'rows_accountant' AND r.code = 'accountant'"
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as client:
        yield {
            "client": client,
            "owner_url": migrated.owner_url,
            "app_role": migrated.app_role,
            "runtime": app.state.runtime,
            **{f"{name}_id": value for name, value in ids.items()},
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def sign_in_admin(world: dict[str, Any]) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": "rows_accountant", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def csrf(world: dict[str, Any]) -> dict[str, str]:
    token = world["client"].cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def an_uploaded_statement(world: dict[str, Any], content: bytes) -> str:
    """A statement whose bytes are really in storage, uploaded through slice 3's route.

    The file object is written directly because M4's upload route is not this slice's subject; the
    *bytes* go through the storage backend rather than being faked, because the parser reads them
    and a test that stubbed the read would be testing a different function.
    """

    from app.files.download import open_stream  # noqa: F401  (import proves the module loads)

    file_id = uuid.uuid4()
    key = f"statements/{file_id}"
    world["runtime"].storage.write(key, io.BytesIO(content))

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, 'statement.xlsx', "
            "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', %s, %s, "
            "'bank_statement', 'internal', 'available', 'clean', 'admin_user', 'original', '{}')",
            (file_id, key, len(content), hashlib.sha256(content).hexdigest()),
        )
        connection.commit()

    response = world["client"].post(
        "/api/v1/bank-statements",
        json={
            "bank_profile_version_id": str(world["version_id"]),
            "bank_account_id": str(world["account_id"]),
            "original_file_id": str(file_id),
        },
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def a_parsed_run(
    world: dict[str, Any], content: bytes, *, mapping_key: str = "mapping"
) -> tuple[str, Any]:
    """Upload, start a run, and let the worker do the parse. Returns the run id and its report."""

    from app.workers.tasks.files import parse_statements

    statement_id = an_uploaded_statement(world, content)
    response = world["client"].post(
        f"/api/v1/bank-statements/{statement_id}/import-runs",
        json={"bank_mapping_id": str(world[f"{mapping_key}_id"])},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 202, response.text
    report = parse_statements(world["runtime"])
    return str(response.json()["id"]), report


def parsed_rows(world: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    records = rows(
        world,
        "SELECT row_number, status, amount_in_irr, amount_out_irr, balance_irr, "
        "transaction_at_normalized, transaction_date_raw, transaction_time_raw, "
        "tracking_number, counterparty_name, raw_data, row_fingerprint "
        "FROM bank_statement_rows WHERE bank_statement_import_run_id = %s ORDER BY row_number",
        run_id,
    )
    keys = (
        "row_number",
        "status",
        "amount_in_irr",
        "amount_out_irr",
        "balance_irr",
        "transaction_at_normalized",
        "transaction_date_raw",
        "transaction_time_raw",
        "tracking_number",
        "counterparty_name",
        "raw_data",
        "row_fingerprint",
    )
    return [dict(zip(keys, record, strict=True)) for record in records]


# --- DB-ROW-001 --------------------------------------------------------------


def test_every_source_line_becomes_a_row(world: dict[str, Any]) -> None:
    """`DB-ROW-001`. §22.2: "never partially hide invalid rows".

    Five source lines, five rows — including the one whose amount is fractional and the one whose
    date is Jalali. A parser that wrote only what it understood would report a `row_count` that
    silently disagreed with the file, and the operator would have no way to see which lines went
    missing.
    """

    sign_in_admin(world)
    run_id, report = a_parsed_run(world, _workbook_bytes(STATEMENT_ROWS))

    assert report.parsed == 1 and report.failed == 0

    stored = parsed_rows(world, run_id)
    assert [row["row_number"] for row in stored] == [1, 2, 3, 4, 5], (
        f"the parse produced rows {[row['row_number'] for row in stored]} from a five-line "
        "statement. Every source line gets a row, whatever the parser made of it."
    )

    run = rows(
        world,
        "SELECT status, row_count, error_summary FROM bank_statement_import_runs WHERE id = %s",
        run_id,
    )[0]
    assert run[0] == "succeeded"
    assert run[1] == 5, f"the run reports {run[1]} rows and wrote {len(stored)}"

    statement_status = rows(
        world,
        "SELECT f.status FROM bank_statement_files f "
        "JOIN bank_statement_import_runs r ON r.bank_statement_file_id = f.id WHERE r.id = %s",
        run_id,
    )[0][0]
    assert statement_status == "parsed", (
        f"the statement file is {statement_status!r} after a successful parse. Document 06 §10.3 "
        "moves it to `parsed` when a run succeeds."
    )


def test_the_runtime_cannot_change_a_parsed_row(world: dict[str, Any]) -> None:
    """`DB-ROW-001`, and §10.6's "immutable" as a privilege rather than a discipline.

    **No UPDATE on any column**, which is a stronger statement than the slice-3 tables make: those
    grant a lifecycle, this grants nothing. A behavioural test cannot see this — the command never
    tries to update a row, so removing the restriction changes no observable behaviour — which is
    exactly why it is read from `information_schema`.
    """

    granted = rows(
        world,
        "SELECT DISTINCT column_name FROM information_schema.column_privileges "
        "WHERE table_name = 'bank_statement_rows' AND privilege_type = 'UPDATE' "
        "AND grantee = %s",
        world["app_role"],
    )
    assert granted == [], (
        f"the runtime may update {[row[0] for row in granted]} on a parsed row. §10.6 calls these "
        "rows immutable and document 08 §8.2 makes a correction a new import run, so there is no "
        "column a later request should be able to edit."
    )


# --- SVC-ROW-001 -------------------------------------------------------------


def test_raw_and_normalized_values_are_both_kept(world: dict[str, Any]) -> None:
    """`SVC-ROW-001`. §18 `:1229`, and document 08 §8.5 three times over.

    The Persian-digit row is the one that proves it: the mapping folds digits, so `amount_in_irr`
    is `3000000000` — and `raw_data` must still hold `۳۰۰۰۰۰۰۰۰۰`. A `raw_data` written from the
    folded reading would look correct in every other test and would have quietly destroyed the only
    copy of what the bank actually wrote.
    """

    sign_in_admin(world)
    run_id, _ = a_parsed_run(world, _workbook_bytes(STATEMENT_ROWS))
    stored = parsed_rows(world, run_id)

    persian = stored[1]
    assert persian["amount_in_irr"] == 3_000_000_000, (
        f"the folded amount is {persian['amount_in_irr']}; Persian digits must normalise to an "
        "integer when the mapping asks for it"
    )
    assert persian["raw_data"]["بستانکار"] == "۳۰۰۰۰۰۰۰۰۰", (
        f"raw_data holds {persian['raw_data']['بستانکار']!r}. §8.5's first rule is 'Preserve every "
        "raw source value', and folding before storing destroys the only copy of the bank's own "
        "text."
    )

    jalali = stored[2]
    assert jalali["transaction_date_raw"] == "1405/05/22"
    assert jalali["transaction_at_normalized"] is None, (
        "a Jalali date was converted to an instant. ADR-006 leaves the calendar conversion "
        "undecided, and inventing one would write an unapproved timestamp into the column slice 5 "
        "matches on."
    )
    assert jalali["status"] == "warning", (
        f"the Jalali row is {jalali['status']!r}. It is matchable by amount and tracking number, "
        "so it is not invalid — but something about it needs a human, so it is not valid either."
    )


def test_an_unmapped_column_still_reaches_raw_data(world: dict[str, Any]) -> None:
    """§22.2: "never partially hide invalid rows", applied to columns rather than rows.

    An unmapped column is usually the first sign a bank changed its file format. Dropping it would
    make that change invisible until somebody compared the spreadsheet by hand.
    """

    sign_in_admin(world)
    run_id, _ = a_parsed_run(world, _workbook_bytes(STATEMENT_ROWS))
    stored = parsed_rows(world, run_id)

    assert stored[0]["raw_data"]["شعبه"] == "۱۲", (
        "a column the mapping does not name was dropped from raw_data"
    )

    summary = rows(
        world, "SELECT error_summary FROM bank_statement_import_runs WHERE id = %s", run_id
    )[0][0]
    assert "شعبه" in summary["unmapped_headers"], (
        f"the run's summary lists unmapped headers {summary['unmapped_headers']}, which omits the "
        "one column the mapping does not name"
    )


def test_a_debit_is_never_read_as_a_credit(world: dict[str, Any]) -> None:
    """§8.5: "Do not silently convert debit to credit or vice versa."

    The two directions come from two mapped columns and are never inferred from a sign. A parser
    that folded them into one signed amount would make an outgoing transfer look like an incoming
    payment, which is the one mistake this whole milestone exists to prevent.
    """

    sign_in_admin(world)
    run_id, _ = a_parsed_run(world, _workbook_bytes(STATEMENT_ROWS))
    outgoing = parsed_rows(world, run_id)[3]

    assert outgoing["amount_out_irr"] == 750_000_000
    assert outgoing["amount_in_irr"] is None, (
        f"an outgoing row reports {outgoing['amount_in_irr']} incoming. A withdrawal that reads as "
        "a deposit would let the centre believe a trader paid when money left instead."
    )


def test_a_fractional_amount_is_flagged_and_not_rounded(world: dict[str, Any]) -> None:
    """§8.5: "Reject or flag decimal/fractional IRR unless explicitly supported."

    Flagged, and the amount left null. Rounding would invent a figure; dropping the row would hide
    a line of the bank's file. The row survives with its raw text, which is what an accountant
    needs in order to ask the bank what it meant.
    """

    sign_in_admin(world)
    run_id, _ = a_parsed_run(world, _workbook_bytes(STATEMENT_ROWS))
    fractional = parsed_rows(world, run_id)[4]

    assert fractional["amount_in_irr"] is None, (
        f"a fractional amount became {fractional['amount_in_irr']}. Rounding invents a figure "
        "nobody wrote."
    )
    assert fractional["status"] == "invalid"
    assert fractional["raw_data"]["بستانکار"] == "1000.5"

    summary = rows(
        world, "SELECT error_summary FROM bank_statement_import_runs WHERE id = %s", run_id
    )[0][0]
    flagged = {entry["row_number"] for entry in summary["rows_with_problems"]}
    assert 5 in flagged, (
        f"the run's error summary names rows {sorted(flagged)} and not row 5. §22.2 requires "
        "import-run errors to be preserved, and a problem nobody can see is not preserved."
    )


def test_an_empty_line_is_ignored_rather_than_invalid(world: dict[str, Any]) -> None:
    """§8.6's `ignored_empty`, and §26.2's "partial blank template rows".

    A bank's template routinely carries trailing blank rows. Calling them `invalid` would fill an
    accountant's preview with problems that are not problems, and the states document 08 defines
    separate the two on purpose.
    """

    sign_in_admin(world)
    run_id, _ = a_parsed_run(
        world, _workbook_bytes([*STATEMENT_ROWS, [None] * len(HEADERS)])
    )
    stored = parsed_rows(world, run_id)

    assert len(stored) == 6
    assert stored[5]["status"] == "ignored_empty", (
        f"the blank line is {stored[5]['status']!r}. A template's trailing blank rows are not "
        "errors, and §8.6 gives them their own state."
    )


def test_two_identical_transfers_share_a_fingerprint(world: dict[str, Any]) -> None:
    """The fingerprint is over the **normalized** values, per §8.4.

    A statement may legitimately contain two identical transfers, so the fingerprint says "look at
    this", not "this is wrong" — slice 4B is what looks. What this asserts is the property that
    makes looking possible: the same transfer written two ways produces one fingerprint, which a
    digest over the raw text would not.

    **The thousands separator is the discriminating difference, and the first version of this test
    used Persian digits instead — which proved nothing.** A negative control replacing the
    normalized digest with `unversioned_digest(raw_data)` went NOT CAUGHT: `app/core/hashing.py`'s
    `normalise_text` folds Persian and Arabic digits to ASCII on the way into *every* digest, so
    the two spellings collide whichever values are hashed. The test was insensitive by
    construction, the fourth meaning of NOT CAUGHT, and the hashing layer was quietly supplying
    the property under test.

    `normalise_text` does not remove commas. So `4,000,000,000` and `۴۰۰۰۰۰۰۰۰۰` differ as raw
    text and agree as parsed integers, which is exactly the gap between the two implementations —
    and Iranian bank statements write both.
    """

    sign_in_admin(world)
    twin = [
        ["2026-08-20", "09:00:00", "4,000,000,000", "", "1", "TRK-2001", "واریز", "الف", "۱"],
        ["2026-08-20", "09:00:00", "۴۰۰۰۰۰۰۰۰۰", "", "1", "TRK-2001", "واریز", "الف", "۱"],
    ]
    run_id, _ = a_parsed_run(world, _workbook_bytes(twin))
    stored = parsed_rows(world, run_id)

    assert len(stored) == 2
    assert stored[0]["amount_in_irr"] == stored[1]["amount_in_irr"] == 4_000_000_000

    # The property this test depends on, asserted rather than assumed. If a future change to
    # `normalise_text` started stripping separators, the two raw copies would collide in every
    # digest and this test would go back to proving nothing — silently, which is the failure it
    # was written to escape.
    from app.core.hashing import normalise_text

    assert normalise_text(stored[0]["raw_data"]["بستانکار"]) != normalise_text(
        stored[1]["raw_data"]["بستانکار"]
    ), (
        "the two raw amounts are indistinguishable once hashed, so a fingerprint over raw_data "
        "would match too and this test cannot tell the two implementations apart"
    )

    assert stored[0]["row_fingerprint"] == stored[1]["row_fingerprint"], (
        "the same transfer written two ways produced two fingerprints. §8.4 calls it a "
        "*normalized* fingerprint, and a digest over the raw text would miss every duplicate a "
        "bank writes with different punctuation."
    )


# --- §22.2, the failure path -------------------------------------------------


def test_a_mapping_that_does_not_fit_fails_the_run_and_writes_no_rows(
    world: dict[str, Any],
) -> None:
    """§22.2: preserve the file, preserve the errors, allow a new run after correction.

    **No rows at all**, which is the difference between a failed run and a bad one. A run that
    wrote the rows it could read and failed afterwards would leave a partial statement in the
    database with nothing marking it partial — and slice 5 would match against it.
    """

    sign_in_admin(world)
    run_id, report = a_parsed_run(
        world, _workbook_bytes(STATEMENT_ROWS), mapping_key="broken_mapping"
    )

    assert report.parsed == 1, (
        "the worker counted a mapping mismatch as a worker failure. The job did what it was asked; "
        "the answer was that this mapping does not fit this file, and retrying it four more times "
        "would produce the same answer."
    )

    run = rows(
        world,
        "SELECT status, row_count, error_summary FROM bank_statement_import_runs WHERE id = %s",
        run_id,
    )[0]
    assert run[0] == "failed"
    assert run[1] == 0
    assert "mapping_error" in run[2], (
        f"the failed run's summary is {run[2]!r} and names no mapping error. §22.2's second "
        "requirement is that import-run errors are preserved."
    )
    assert "مبلغ واریزی" in run[2]["mapping_error"], (
        "the error does not name the missing column, so an operator is told the mapping is wrong "
        "without being told which part"
    )

    assert parsed_rows(world, run_id) == [], (
        "a failed run wrote rows. A partial statement nothing marks as partial is worse than none."
    )

    statement_status = rows(
        world,
        "SELECT f.status FROM bank_statement_files f "
        "JOIN bank_statement_import_runs r ON r.bank_statement_file_id = f.id WHERE r.id = %s",
        run_id,
    )[0][0]
    assert statement_status == "parse_failed"


def test_a_corrected_mapping_reparses_the_same_file(world: dict[str, Any]) -> None:
    """§22.2's third requirement, end to end: "allow new import run after mapping correction".

    The same statement, first with a mapping that does not fit and then with one that does. Run 1's
    record must be untouched afterwards — slice 3's property, re-asserted here because this is the
    first test in which run 1 has actually *done* something and could therefore be overwritten by
    something that looks like a retry.
    """

    from app.workers.tasks.files import parse_statements

    sign_in_admin(world)
    content = _workbook_bytes(STATEMENT_ROWS)
    statement_id = an_uploaded_statement(world, content)

    first = world["client"].post(
        f"/api/v1/bank-statements/{statement_id}/import-runs",
        json={"bank_mapping_id": str(world["broken_mapping_id"])},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert first.status_code == 202, first.text
    parse_statements(world["runtime"])
    first_id = first.json()["id"]

    before = rows(
        world,
        "SELECT status, row_count, parser_version, source_hash, bank_mapping_id, error_summary "
        "FROM bank_statement_import_runs WHERE id = %s",
        first_id,
    )[0]
    assert before[0] == "failed"

    second = world["client"].post(
        f"/api/v1/bank-statements/{statement_id}/import-runs",
        json={"bank_mapping_id": str(world["mapping_id"])},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert second.status_code == 202, (
        f"the corrected mapping could not be run: {second.text}. §22.2 requires a new import run "
        "after a mapping correction, and a failed run is not in flight."
    )
    parse_statements(world["runtime"])

    assert second.json()["run_number"] == 2
    assert parsed_rows(world, second.json()["id"]) != []

    after = rows(
        world,
        "SELECT status, row_count, parser_version, source_hash, bank_mapping_id, error_summary "
        "FROM bank_statement_import_runs WHERE id = %s",
        first_id,
    )[0]
    assert after == before, (
        f"the failed run changed when the corrected one ran. Before: {before!r}. After: {after!r}. "
        "Document 08 §8.2: reprocessing never overwrites earlier rows."
    )


def test_another_tasks_job_is_handed_back(world: dict[str, Any]) -> None:
    """Two tasks now share the `files` queue, and neither may fail the other's work.

    `claim_jobs` takes whatever is due on the queue, not whatever the caller understands. So the
    parse task claims crop jobs and the crop task claims parse jobs, and each must release what it
    does not recognise. Failing it instead would consume that job's attempts on a worker that never
    tried it — three passes and a crop dead-letters having never been rendered.

    The crop job here is never rendered; only its status after a parse pass is the subject.
    """

    from app.workers.tasks.files import parse_statements

    sign_in_admin(world)
    job_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO processing_jobs (id, job_type, queue_name, status, input_payload, "
            "max_attempts) VALUES (%s, 'receipt_segment.render_crop', 'files', 'queued', "
            "'{\"receipt_segment_id\": \"00000000-0000-4000-8000-000000000001\"}', 5)",
            (job_id,),
        )
        connection.commit()

    parse_statements(world["runtime"])

    status, attempts = rows(
        world, "SELECT status, attempt_count FROM processing_jobs WHERE id = %s", job_id
    )[0]
    assert status != "dead_lettered", (
        "the parse task dead-lettered a crop job. `claim_jobs` hands out whatever is due on the "
        "queue, so each task must release what it does not recognise rather than failing it."
    )
    assert attempts <= 1, (
        f"the crop job has {attempts} attempts recorded after a parse pass that never tried it"
    )


def test_a_mapping_naming_an_unknown_field_never_reaches_a_row(world: dict[str, Any]) -> None:
    """The allowlist, and `tests/fixtures/bank_fixtures.py` is why it exists.

    That file carries a mapping whose `field` is `amount_irr"; DROP TABLE bank_mappings; --`,
    deliberately, "a mapping value that must never reach SQL as an identifier". The parser produces
    a fixed set of fields and nothing else, so an unknown name is a configuration error that fails
    the run before a single row is written — enforcement by absence rather than by escaping.
    """

    import json

    from app.workers.tasks.files import parse_statements

    sign_in_admin(world)
    hostile_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO bank_mappings (id, bank_profile_version_id, file_type, "
            "template_version, status, mapping, config_hash) "
            "VALUES (%s, %s, 'statement_import', 3, 'active', %s, %s)",
            (
                hostile_id,
                world["version_id"],
                json.dumps(
                    {
                        "columns": [
                            {"header": "تاریخ", "field": "transaction_date"},
                            {
                                "header": "مبلغ",
                                "field": 'amount_irr"; DROP TABLE bank_mappings; --',
                            },
                        ]
                    }
                ),
                hashlib.sha256(b"hostile").hexdigest(),
            ),
        )
        connection.commit()

    statement_id = an_uploaded_statement(world, _workbook_bytes(STATEMENT_ROWS))
    response = world["client"].post(
        f"/api/v1/bank-statements/{statement_id}/import-runs",
        json={"bank_mapping_id": str(hostile_id)},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 202, response.text
    parse_statements(world["runtime"])

    run = rows(
        world,
        "SELECT status, error_summary FROM bank_statement_import_runs WHERE id = %s",
        response.json()["id"],
    )[0]
    assert run[0] == "failed"
    assert "does not produce" in run[1]["mapping_error"]
    assert parsed_rows(world, str(response.json()["id"])) == []

    # The table the mapping asked to drop is still there, which is the point of naming it in the
    # fixture: the parser never treated the value as anything but a string to compare.
    assert rows(world, "SELECT count(*) FROM bank_mappings")[0][0] >= 3
