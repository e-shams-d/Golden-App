"""A duplicate is a warning, and a warning is somebody's work.
`08_Bank_File_and_Result_Processing.md` §8.7.

M10 slice 4B, against a real PostgreSQL and real `.xlsx` files.

**The section's last line governs the whole slice: "A warning does not automatically delete or
merge data."** So every test here checks two things — that the signal fired, *and* that the data
is still there. A detector that quietly dropped the repeat would satisfy every "duplicates are
detected" assertion anybody would think to write.

**The hardest property is the one about reparsing.** Document 08 §8.2 makes reprocessing the
specified workflow, so run 2 of a file produces the same fingerprints as run 1 every single time.
A detector comparing against every earlier row would flag every reparse completely, which would
train an accountant to ignore the warning — the worst outcome available.
`test_a_reparse_is_not_a_duplicate_of_itself` is why the query excludes other runs of the same
statement file.

Covers: SVC-FINGERPRINT-001.
"""

from __future__ import annotations

import hashlib
import io
import json
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

HEADERS = ["date", "amount_in", "tracking", "who"]

MAPPING: dict[str, Any] = {
    "columns": [
        {"header": "date", "field": "transaction_date"},
        {"header": "amount_in", "field": "amount_in_irr"},
        {"header": "tracking", "field": "tracking_number"},
        {"header": "who", "field": "counterparty_name"},
    ]
}


def a_row(day: int, amount: int, tracking: str, who: str = "Payer") -> list[Any]:
    return [f"2026-08-{day:02d}", str(amount), tracking, who]


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


def workbook_bytes(rows: list[list[Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
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

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path_factory.mktemp("dup-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="u" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {name: uuid.uuid4() for name in ("bank", "version", "account", "mapping")}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'dupbank', 'Dup Bank', 'active')",
            (ids["bank"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "config_hash) VALUES (%s, %s, 1, 'active', %s)",
            (ids["version"], ids["bank"], hashlib.sha256(b"dup-version").hexdigest()),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, account_role, status) "
            "VALUES (%s, %s, 'Incoming', 'incoming_destination', 'active')",
            (ids["account"], ids["bank"]),
        )
        connection.execute(
            "INSERT INTO bank_mappings (id, bank_profile_version_id, file_type, "
            "template_version, status, mapping, config_hash) "
            "VALUES (%s, %s, 'statement_import', 1, 'active', %s, %s)",
            (
                ids["mapping"],
                ids["version"],
                json.dumps(MAPPING),
                hashlib.sha256(b"dup-mapping").hexdigest(),
            ),
        )
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES ('dup_accountant', 'Accountant', %s, 'active')",
            (encoded,),
        )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'dup_accountant' AND r.code = 'accountant'"
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as client:
        yield {
            "client": client,
            "owner_url": migrated.owner_url,
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
        json={"identifier": "dup_accountant", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def csrf(world: dict[str, Any]) -> dict[str, str]:
    token = world["client"].cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def upload(world: dict[str, Any], content: bytes) -> str:
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


def parse(world: dict[str, Any], statement_id: str) -> str:
    from app.workers.tasks.files import parse_statements

    response = world["client"].post(
        f"/api/v1/bank-statements/{statement_id}/import-runs",
        json={"bank_mapping_id": str(world["mapping_id"])},
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 202, response.text
    parse_statements(world["runtime"])
    return str(response.json()["id"])


def imported(world: dict[str, Any], content: bytes) -> tuple[str, str]:
    statement_id = upload(world, content)
    return statement_id, parse(world, statement_id)


def statuses(world: dict[str, Any], run_id: str) -> list[str]:
    return [
        row[0]
        for row in rows(
            world,
            "SELECT status FROM bank_statement_rows WHERE bank_statement_import_run_id = %s "
            "ORDER BY row_number",
            run_id,
        )
    ]


def tasks_for(world: dict[str, Any], entity_id: str) -> list[tuple[Any, ...]]:
    return rows(
        world,
        "SELECT task_type, entity_type, status, title, description FROM manual_review_tasks "
        "WHERE entity_id = %s",
        entity_id,
    )


def summary_of(world: dict[str, Any], run_id: str) -> dict[str, Any]:
    return rows(
        world, "SELECT error_summary FROM bank_statement_import_runs WHERE id = %s", run_id
    )[0][0]


# --- SVC-FINGERPRINT-001 -----------------------------------------------------


def test_a_repeated_line_is_flagged_and_kept(world: dict[str, Any]) -> None:
    """`SVC-FINGERPRINT-001`, and §8.7's last line.

    **Both halves, and the second is the one that matters.** The repeat is marked
    `possible_duplicate` — and it is still there, with its own row number and its own raw copy. A
    detector that deduplicated on the way in would pass any assertion about the *first* row while
    destroying the evidence an accountant needs to decide whether the bank sent the transfer twice
    or the operator uploaded it twice.

    Only the **second** occurrence is flagged. Flagging both would double every count and leave an
    accountant with no way to see which line is the original.
    """

    sign_in_admin(world)
    marker = uuid.uuid4().hex[:8]
    _, run_id = imported(
        world,
        workbook_bytes(
            [
                a_row(1, 1_000_000_000, f"A-{marker}"),
                a_row(2, 2_000_000_000, f"B-{marker}"),
                # Byte-identical to the first line.
                a_row(1, 1_000_000_000, f"A-{marker}"),
            ]
        ),
    )

    assert statuses(world, run_id) == ["valid", "valid", "possible_duplicate"], (
        f"statuses were {statuses(world, run_id)}. Only the repeat is flagged, and it is flagged "
        "rather than removed."
    )

    stored = rows(
        world,
        "SELECT row_number, amount_in_irr, tracking_number FROM bank_statement_rows "
        "WHERE bank_statement_import_run_id = %s ORDER BY row_number",
        run_id,
    )
    assert len(stored) == 3, (
        f"{len(stored)} rows survived a three-line statement. §8.7: a warning does not "
        "automatically delete or merge data."
    )
    assert stored[2][1] == 1_000_000_000 and stored[2][2] == f"A-{marker}", (
        "the flagged row lost its values, so the evidence an accountant needs is gone"
    )


def test_the_duplicate_opens_one_task_for_the_run(world: dict[str, Any]) -> None:
    """§8.7 leaves the decision to a person, so a person has to be told.

    **One task for the run, not one per row.** A statement whose last week overlaps the previous
    upload produces forty findings and one question; forty queue items would bury it. The
    description names the rows so the task is actionable without opening the parse.
    """

    sign_in_admin(world)
    marker = uuid.uuid4().hex[:8]
    _, run_id = imported(
        world,
        workbook_bytes(
            [
                a_row(3, 5_000_000_000, f"C-{marker}"),
                a_row(3, 5_000_000_000, f"C-{marker}"),
                a_row(4, 6_000_000_000, f"D-{marker}"),
                a_row(4, 6_000_000_000, f"D-{marker}"),
            ]
        ),
    )

    opened = tasks_for(world, run_id)
    assert len(opened) == 1, (
        f"{len(opened)} tasks were opened for one run with two duplicates. One question deserves "
        "one queue item."
    )
    task_type, entity_type, status, title, description = opened[0]
    assert task_type == "statement_duplicate_review"
    assert entity_type == "bank_statement_import_run"
    assert status == "open"
    assert "2" in title
    # Rows **2 and 4** — the repeats, not the originals. Lines 1 and 3 are the first occurrences
    # and are not the ones an accountant has to decide about.
    assert "rows 2, 4" in description, (
        f"the task description is {description!r} and does not name the repeated rows, so an "
        "accountant cannot act on it without opening the parse themselves"
    )


def test_a_reparse_is_not_a_duplicate_of_itself(world: dict[str, Any]) -> None:
    """The property the whole detector is shaped around. Document 08 §8.2.

    Reprocessing is the *specified* workflow: run 2 reads the same bytes and produces the same
    fingerprints as run 1, every time. A detector comparing against every earlier row would flag
    every row of every reparse — and an accountant who sees a whole statement flagged twice learns
    to ignore the flag, which is worse than not having one.
    """

    sign_in_admin(world)
    marker = uuid.uuid4().hex[:8]
    content = workbook_bytes(
        [a_row(5, 7_000_000_000, f"E-{marker}"), a_row(6, 8_000_000_000, f"F-{marker}")]
    )
    statement_id, first_run = imported(world, content)
    assert statuses(world, first_run) == ["valid", "valid"]

    second_run = parse(world, statement_id)

    assert statuses(world, second_run) == ["valid", "valid"], (
        f"the reparse produced {statuses(world, second_run)}. Document 08 §8.2 makes reprocessing "
        "the specified workflow; flagging it teaches an accountant to ignore the warning."
    )
    assert tasks_for(world, second_run) == [], (
        "a reparse opened a duplicate review. Every reparse would, and the queue would fill with "
        "the one thing the documents tell operators to do."
    )


def test_the_same_transfer_in_a_second_statement_is_flagged(world: dict[str, Any]) -> None:
    """The overlapping-period case, which is the one that actually happens.

    An operator uploads August, then uploads a July-to-August export, and the last week arrives
    twice. Different files, so the reparse exclusion above does not apply — and this is exactly the
    case that exclusion must not swallow.
    """

    sign_in_admin(world)
    marker = uuid.uuid4().hex[:8]
    shared = a_row(7, 9_000_000_000, f"G-{marker}")

    _, first_run = imported(world, workbook_bytes([shared, a_row(8, 1, f"H-{marker}")]))
    assert statuses(world, first_run) == ["valid", "valid"]

    _, second_run = imported(world, workbook_bytes([a_row(9, 2, f"I-{marker}"), shared]))

    assert statuses(world, second_run) == ["valid", "possible_duplicate"], (
        f"the second statement produced {statuses(world, second_run)}. A transfer already imported "
        "from another file is the overlapping-period case §8.7 exists for."
    )

    signals = {entry["signal"] for entry in summary_of(world, second_run)["duplicate_signals"]}
    assert "same_fingerprint_in_another_statement" in signals, (
        f"the run's summary names signals {signals} and not the cross-statement one, so an "
        "operator is told a row is suspect without being told why"
    )


def test_a_shared_tracking_number_is_its_own_signal(world: dict[str, Any]) -> None:
    """§8.7's fourth signal: "same tracking/document number".

    Separate from the fingerprint because it catches what the fingerprint cannot: a bank re-sending
    one transfer with a corrected date or amount. The rows differ, so the fingerprints differ, and
    the reference is the only thing that says they are the same event.
    """

    sign_in_admin(world)
    marker = uuid.uuid4().hex[:8]
    _, run_id = imported(
        world,
        workbook_bytes(
            [
                a_row(10, 3_000_000_000, f"J-{marker}"),
                # Same tracking number, different day and different amount: not the same
                # fingerprint, and the bank says it is the same transfer.
                a_row(11, 3_500_000_000, f"J-{marker}"),
            ]
        ),
    )

    assert statuses(world, run_id) == ["valid", "possible_duplicate"]
    signals = {entry["signal"] for entry in summary_of(world, run_id)["duplicate_signals"]}
    assert signals == {"same_tracking_or_document_number"}, (
        f"the signals were {signals}. The fingerprints differ here, so the tracking number is the "
        "only thing that could have caught it — and naming the fingerprint would be wrong."
    )


def test_the_same_file_uploaded_twice_opens_its_own_task(world: dict[str, Any]) -> None:
    """§8.7's first signal, and §26.2's "duplicate file checksum" test case.

    A different question from the row signals, with a different answer: not "are these rows already
    here" but "should this upload exist at all". So it names the **statement file**, and it fires
    on the file's own sha256 rather than on anything the parse produced.
    """

    sign_in_admin(world)
    marker = uuid.uuid4().hex[:8]
    content = workbook_bytes([a_row(12, 4_400_000_000, f"K-{marker}")])

    first_statement, _ = imported(world, content)
    second_statement, _ = imported(world, content)

    opened = tasks_for(world, second_statement)
    assert len(opened) == 1, (
        f"{len(opened)} tasks were opened for a byte-identical re-upload. §26.2 names 'duplicate "
        "file checksum' as a case this import must handle."
    )
    assert opened[0][1] == "bank_statement_file"
    assert first_statement in opened[0][4], (
        f"the task description is {opened[0][4]!r} and does not name the statement this file "
        "duplicates, so the operator cannot compare them"
    )

    assert tasks_for(world, first_statement) == [], (
        "the *first* upload was flagged as a duplicate of the second. The question is about the "
        "one that arrived later."
    )

    # **A third upload, and it must name the first.** With only two copies this test could not tell
    # `created_at ASC` from `DESC` — both return the one other row — and a control flipping the
    # order went NOT CAUGHT for exactly that reason: the sabotage did not break the property the
    # fixture could reach. An operator retrying an upload twice is ordinary, and the useful answer
    # names the original rather than whichever copy happens to sort first.
    third_statement, _ = imported(world, content)
    third_task = tasks_for(world, third_statement)
    assert len(third_task) == 1
    assert first_statement in third_task[0][4], (
        f"the third upload's task is {third_task[0][4]!r}. With three identical files the answer "
        f"must be the original ({first_statement}), not the most recent copy ({second_statement})."
    )


def test_a_clean_statement_opens_nothing(world: dict[str, Any]) -> None:
    """The other half of every assertion above, and the one that keeps them meaningful.

    A detector that flagged everything would satisfy every test in this module. This is the control
    that makes the rest of them evidence: an ordinary statement produces no `possible_duplicate`
    row, no task, and an empty signal list.
    """

    sign_in_admin(world)
    marker = uuid.uuid4().hex[:8]
    _, run_id = imported(
        world,
        workbook_bytes(
            [
                a_row(13, 1_100_000_000, f"L-{marker}"),
                a_row(14, 1_200_000_000, f"M-{marker}"),
                a_row(15, 1_300_000_000, f"N-{marker}"),
            ]
        ),
    )

    assert statuses(world, run_id) == ["valid", "valid", "valid"]
    assert tasks_for(world, run_id) == []
    assert summary_of(world, run_id)["duplicate_signals"] == []
    assert summary_of(world, run_id)["duplicate_of_statement_file_id"] is None


def test_an_unreadable_row_stays_invalid_even_when_repeated(world: dict[str, Any]) -> None:
    """`invalid` outranks `possible_duplicate`, and the order matters.

    A row that could not be read is a bigger problem than a row that looks familiar. If a repeated
    unreadable line became `possible_duplicate`, the fact that nobody can read it would disappear
    from the preview — and §22.2's "never partially hide invalid rows" is about exactly that kind
    of disappearance.
    """

    sign_in_admin(world)
    marker = uuid.uuid4().hex[:8]
    _, run_id = imported(
        world,
        workbook_bytes(
            [
                ["2026-08-16", "not-a-number", f"O-{marker}", "Payer"],
                ["2026-08-16", "not-a-number", f"O-{marker}", "Payer"],
            ]
        ),
    )

    assert statuses(world, run_id) == ["invalid", "invalid"], (
        f"statuses were {statuses(world, run_id)}. A repeated unreadable row must stay invalid; "
        "otherwise the reason nobody can read it vanishes from the preview."
    )
