"""The statement the centre imports, and the run that never overwrites the last one.

M10 slice 3, against a real PostgreSQL. `05_API_Specification.md` §21.4, `04_Database_Schema.md`
§10.4-10.5, `06_Workflows_and_State_Machines.md` §10, `08_Bank_File_and_Result_Processing.md` §8.

**The slice is one sentence and one test.** Document 08 §8.2: "Reprocessing never overwrites
earlier rows. It creates a new import run." So `test_a_reparse_never_touches_the_first_run` reads
run 1 back **field by field** after run 2 exists and requires every column to be byte-identical.
A test that only checked run 2 was created would pass against an implementation that helpfully
updated run 1 in place, which is the shape this repository has met four times.

**The row-level half of that claim is slice 4's**, and saying so here matters: rows do not exist
yet, so "run 1's rows are unchanged" is unprovable and is not asserted. What is provable now is
that run 1's own record — its number, its parser, its source hash, its mapping — is untouched, and
that is what these tests hold.

Covers: DB-IMPORT-001, SVC-IMPORT-001, TRACE-IMPORT-001, SEC-IMPORT-001.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "X-CSRF-Token"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"

TRADER_PHONE = "+989120014001"

STATEMENT_SHA = "b" * 64


def _hash(label: str) -> str:
    """A real lowercase-hex digest.

    `bank_profile_versions` and `bank_mappings` both CHECK `config_hash` for lowercase hex, so a
    padded label is refused. Derived from the fixture's own name so the value is stable across
    runs and says where it came from.
    """

    return hashlib.sha256(label.encode("utf-8")).hexdigest()


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
        local_storage_root=tmp_path_factory.mktemp("statement-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="s" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids = {
        name: uuid.uuid4()
        for name in (
            "our_bank",
            "other_bank",
            "our_version",
            "other_version",
            "incoming_account",
            "outgoing_account",
            "other_bank_account",
            "statement_mapping",
            "draft_mapping",
            "export_mapping",
            "other_version_mapping",
            "statement_file_object",
            "unscanned_file_object",
            "trader",
        )
    }

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        # Two banks, so "a mapping from another bank's version" and "an account at another bank"
        # are things the fixture can actually express. A single-bank world cannot fail those
        # guards, and a guard whose fixture cannot reach it is untested.
        for key, code, name in (
            # Lowercase codes: `ck_bank_profiles_code_is_lowercase` is M2's, and a fixture that
            # ignored it would be building a world the schema refuses.
            ("our_bank", "ourb", "Our Bank"),
            ("other_bank", "othb", "Other Bank"),
        ):
            connection.execute(
                "INSERT INTO bank_profiles (id, code, name, status) VALUES (%s, %s, %s, 'active')",
                (ids[key], code, name),
            )
        for key, bank_key in (
            ("our_version", "our_bank"),
            ("other_version", "other_bank"),
        ):
            connection.execute(
                "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
                "config_hash) VALUES (%s, %s, 1, 'active', %s)",
                (ids[key], ids[bank_key], _hash(key)),
            )
        for key, bank_key, role, label in (
            ("incoming_account", "our_bank", "incoming_destination", "Incoming"),
            ("outgoing_account", "our_bank", "outgoing_source", "Outgoing"),
            ("other_bank_account", "other_bank", "incoming_destination", "Other Incoming"),
        ):
            connection.execute(
                "INSERT INTO bank_accounts (id, bank_profile_id, display_name, account_role, "
                "status) VALUES (%s, %s, %s, %s, 'active')",
                (ids[key], ids[bank_key], label, role),
            )
        # Four mappings, one usable. Each of the other three fails exactly one guard, so a control
        # that removes a guard has a fixture that reaches it.
        for key, version_key, file_type, status, template in (
            ("statement_mapping", "our_version", "statement_import", "active", 1),
            ("draft_mapping", "our_version", "statement_import", "draft", 2),
            ("export_mapping", "our_version", "outgoing_export", "active", 1),
            ("other_version_mapping", "other_version", "statement_import", "active", 1),
        ):
            connection.execute(
                "INSERT INTO bank_mappings (id, bank_profile_version_id, file_type, "
                "template_version, status, mapping, config_hash) "
                "VALUES (%s, %s, %s, %s, %s, '{}', %s)",
                (ids[key], ids[version_key], file_type, template, status, _hash(key)),
            )
        # `ck_file_objects_available_requires_clean_scan` is M4's, and it means the unscanned
        # fixture cannot also be `available` — which is the honest shape anyway: a file whose scan
        # has not finished is not yet a file the platform will serve.
        for key, storage, scan in (
            ("statement_file_object", "available", "clean"),
            ("unscanned_file_object", "pending", "pending"),
        ):
            _insert_file(connection, ids[key], storage=storage, scan=scan)
        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES ('statement_accountant', 'Accountant', %s, 'active')",
            (encoded,),
        )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'statement_accountant' AND r.code = 'accountant'"
        )
        # A trader, so "no trader may see a statement" is a claim a test can make rather than one
        # the router's docstring asserts.
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Curious Trader', %s, 'active', 'approved')",
            (ids["trader"], TRADER_PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Curious Contact', %s, 'active', TRUE)",
            (ids["trader"], TRADER_PHONE, encoded),
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
            **{f"{name}_id": value for name, value in ids.items()},
        }
    app.state.runtime.close()


def _insert_file(
    connection: Any, file_id: uuid.UUID, *, storage: str = "available", scan: str = "clean"
) -> uuid.UUID:
    connection.execute(
        "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
        "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
        "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
        "original_or_derived_relation, metadata) "
        "VALUES (%s, 'local', 'gold', %s, 'statement.xlsx', "
        "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 4096, %s, "
        "'bank_statement', 'internal', %s, %s, 'admin_user', 'original', '{}')",
        (file_id, f"statements/{file_id}", STATEMENT_SHA, storage, scan),
    )
    return file_id


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def a_fresh_file(world: dict[str, Any]) -> str:
    """A statement upload nothing has claimed yet.

    `bank_statement_files.original_file_id` is unique — two statement records pointing at one
    upload would each claim to be the original of it — and this module's fixture is module-scoped,
    so a shared file object makes the second test fail on the first one's row. Found exactly that
    way, by the constraint this slice added.
    """

    file_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        _insert_file(connection, file_id)
        connection.commit()
    return str(file_id)


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def sign_in_admin(world: dict[str, Any]) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login",
        json={"identifier": "statement_accountant", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def sign_in_trader(world: dict[str, Any]) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": TRADER_PHONE, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(world: dict[str, Any]) -> dict[str, str]:
    client = world["client"]
    token = client.cookies.get(ADMIN_CSRF_COOKIE) or client.cookies.get(TRADER_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def upload_statement(world: dict[str, Any], **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "bank_profile_version_id": str(world["our_version_id"]),
        "bank_account_id": str(world["incoming_account_id"]),
        "original_file_id": str(world["statement_file_object_id"]),
    }
    body.update(overrides)
    return world["client"].post(
        "/api/v1/bank-statements",
        json=body,
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )


def a_statement(world: dict[str, Any]) -> str:
    """An uploaded statement, through the route rather than around it."""

    response = upload_statement(world, original_file_id=a_fresh_file(world))
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def start_run(world: dict[str, Any], statement_id: str, **overrides: Any) -> Any:
    body: dict[str, Any] = {"bank_mapping_id": str(world["statement_mapping_id"])}
    body.update(overrides)
    return world["client"].post(
        f"/api/v1/bank-statements/{statement_id}/import-runs",
        json=body,
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )


def finish_run(world: dict[str, Any], run_id: str, *, status: str = "succeeded") -> None:
    """Move a run out of flight, as the worker slice 4 builds will.

    Written directly because the worker does not exist yet. Every test that needs a *second* run
    needs this first — the in-flight guard is deliberate, and a fixture that bypassed it by
    inserting runs directly would also bypass `_next_run_number`, which is what
    `DB-IMPORT-001` is about.
    """

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE bank_statement_import_runs SET status = %s, row_count = 3, "
            "started_at = now(), finished_at = now() WHERE id = %s",
            (status, run_id),
        )
        connection.commit()


def run_record(world: dict[str, Any], run_id: str) -> tuple[Any, ...]:
    return rows(
        world,
        "SELECT run_number, status, row_count, parser_version, source_hash, bank_mapping_id, "
        "started_at, finished_at, error_summary, created_at "
        "FROM bank_statement_import_runs WHERE id = %s",
        run_id,
    )[0]


# --- DB-IMPORT-001 -----------------------------------------------------------


def test_the_first_run_is_number_one_and_the_second_is_number_two(
    world: dict[str, Any],
) -> None:
    """`DB-IMPORT-001`. §10.5's `UNIQUE(bank_statement_file_id, run_number)`."""

    sign_in_admin(world)
    statement_id = a_statement(world)

    first = start_run(world, statement_id)
    assert first.status_code == 202, first.text
    assert first.json()["run_number"] == 1
    assert first.json()["status"] == "queued"
    finish_run(world, first.json()["id"])

    second = start_run(world, statement_id)
    assert second.status_code == 202, second.text
    assert second.json()["run_number"] == 2, (
        "the second parse did not get its own number. §10.5 makes every parse a separate run, "
        "and a reused number is how one parse overwrites another."
    )
    assert second.json()["id"] != first.json()["id"]


def test_run_numbers_are_per_file_not_global(world: dict[str, Any]) -> None:
    """`DB-IMPORT-001`. The unique is scoped to the file, and so is the counter.

    A global counter would number a second statement's first parse `2`, and an operator reading
    "run 2" would look for a run 1 of a file that only ever had one.
    """

    sign_in_admin(world)
    first_statement = a_statement(world)
    other_statement = a_statement(world)

    start_run(world, first_statement)
    second = start_run(world, other_statement)

    assert second.status_code == 202, second.text
    assert second.json()["run_number"] == 1, (
        "a second statement's first parse was numbered as though it followed the first "
        "statement's. Run numbers are per file."
    )


def test_a_deleted_run_does_not_free_its_number(world: dict[str, Any]) -> None:
    """`DB-IMPORT-001`. The counter reads the highest number, it does not count rows.

    **This test exists because a negative control went NOT CAUGHT.** Replacing `max(run_number)`
    with `count(run_number)` changed nothing any other test could see: while no run is ever
    deleted the two are identical, so the control was the third meaning — a sabotage that does not
    break the property as the suite can reach it.

    The state is reachable in production. Document 08 §24 lists "import runs and rows" among the
    objects a retention policy covers, so a purged run is a thing that happens, and after one the
    two implementations diverge.

    **Run 1 is what gets purged, and the first version of this test purged run 2 instead — which
    made it fail against the correct implementation as well.** Deleting the *highest* run lowers
    the maximum too, so both readings return the same number and neither collides, because nothing
    occupies it. The discriminating case is a hole in the middle: with runs 1 and 2 present and
    run 1 removed, `max` gives 3 and `count` gives 2 — and 2 is taken. A control reported CAUGHT
    against the broken test, which proves nothing: a test that fails against everything catches
    everything.

    So `max` is not a promise that numbers are never reused. It is the narrower and true one: a
    number still in use is never handed out twice.
    """

    sign_in_admin(world)
    statement_id = a_statement(world)

    first = start_run(world, statement_id)
    finish_run(world, first.json()["id"])
    second = start_run(world, statement_id)
    finish_run(world, second.json()["id"])
    assert second.json()["run_number"] == 2

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "DELETE FROM bank_statement_import_runs WHERE id = %s", (first.json()["id"],)
        )
        connection.commit()

    third = start_run(world, statement_id)
    assert third.status_code == 202, third.text
    assert third.json()["run_number"] == 3, (
        f"the next run was numbered {third.json()['run_number']} after run 1 was purged, and run "
        "2 still exists. A counter that reuses a live number collides on the unique, and the "
        "operator sees a constraint name rather than anything they can act on."
    )


# --- SVC-IMPORT-001 ----------------------------------------------------------


def test_a_reparse_never_touches_the_first_run(world: dict[str, Any]) -> None:
    """`SVC-IMPORT-001`. §10.5 `:774`, doc 06 §10.3, doc 08 §8.2.

    **The slice's whole point, and the reason it reads every column back.** Run 1 is finished, run
    2 is created, and run 1's record must be identical afterwards — not merely present. An
    implementation that reused the row and bumped its `parser_version` would leave a run that says
    it was produced by a parser it was not, which is precisely what `TRACE-IMPORT-001` exists to
    prevent and what a create-only test would miss.
    """

    sign_in_admin(world)
    statement_id = a_statement(world)

    first = start_run(world, statement_id)
    assert first.status_code == 202, first.text
    first_id = first.json()["id"]
    finish_run(world, first_id)

    before = run_record(world, first_id)
    assert before[1] == "succeeded"

    second = start_run(world, statement_id)
    assert second.status_code == 202, second.text
    assert second.json()["id"] != first_id

    after = run_record(world, first_id)
    assert after == before, (
        "the first run's record changed when the second was created. Document 08 §8.2: "
        f"'Reprocessing never overwrites earlier rows.' Before: {before!r}. After: {after!r}."
    )

    both = rows(
        world,
        "SELECT run_number FROM bank_statement_import_runs WHERE bank_statement_file_id = %s "
        "ORDER BY run_number",
        statement_id,
    )
    assert [row[0] for row in both] == [1, 2], (
        "a reparse must leave two runs, not replace one. Found: " f"{[row[0] for row in both]}"
    )


def test_a_second_run_cannot_start_while_one_is_in_flight(world: dict[str, Any]) -> None:
    """The implementation's own guard, and the plan records it as the implementation's.

    Neither document forbids two concurrent parses. Both are silent, and the result is ambiguous:
    two row sets for one file with nothing saying which is authoritative. Refused rather than
    resolved arbitrarily.
    """

    sign_in_admin(world)
    statement_id = a_statement(world)

    first = start_run(world, statement_id)
    assert first.status_code == 202, first.text

    second = start_run(world, statement_id)
    assert second.status_code == 400, second.text
    assert "queued" in second.text

    finish_run(world, first.json()["id"], status="failed")
    third = start_run(world, statement_id)
    assert third.status_code == 202, (
        "a failed run blocked the reparse that was supposed to fix it. Only a run still in "
        "flight blocks; document 08 §22.2 specifically allows a new run after mapping correction."
    )


# --- TRACE-IMPORT-001 --------------------------------------------------------


def test_the_run_records_which_parser_read_which_bytes(world: dict[str, Any]) -> None:
    """`TRACE-IMPORT-001`. §10.5's `parser_version` and `source_hash`.

    M8's `renderer_version` precedent: a row must be tellable apart from one a later parser
    produced against the same file. Both columns are asserted **non-empty and equal to the file's
    own digest** — a run recording a hash of its own invention would satisfy a not-null check and
    prove nothing.
    """

    sign_in_admin(world)
    statement_id = a_statement(world)

    response = start_run(world, statement_id)
    assert response.status_code == 202, response.text
    body = response.json()

    assert body["parser_version"], "the run recorded no parser version"
    assert body["source_hash"] == STATEMENT_SHA, (
        f"the run recorded source hash {body['source_hash']!r}; the file's own sha256 is "
        f"{STATEMENT_SHA!r}. A hash that does not come from the file cannot show that two runs "
        "read the same bytes."
    )
    assert body["row_count"] is None, (
        "a queued run reported a row count. Zero would say it parsed and found none; null is the "
        "only honest answer before a parser has run."
    )
    assert body["created_by_job_id"] is not None, (
        "no job was enqueued, so nothing will ever parse this run"
    )

    job = rows(
        world,
        "SELECT job_type, queue_name, status, provider_version, input_entity_type "
        "FROM processing_jobs WHERE id = %s",
        body["created_by_job_id"],
    )[0]
    assert job[0] == "bank_statement.parse_import_run"
    assert job[1] == "files"
    assert job[2] == "queued"
    assert job[3] == body["parser_version"], (
        "the job and the run disagree about which parser will read the file, so the run's "
        "provenance would not describe the parse that actually happened"
    )
    assert job[4] == "bank_statement_import_run"


def test_the_audit_entry_carries_the_provenance(world: dict[str, Any]) -> None:
    """`TRACE-IMPORT-001`, and the catalogued name.

    `audit_outbox_catalog.yaml:57` names `bank_statement.import_run_created` and
    `command_catalog.yaml` maps it to this exact route. Nothing is declared for it — the first M10
    command for which that is true — so the assertion is on the catalogued spelling.
    """

    sign_in_admin(world)
    statement_id = a_statement(world)
    response = start_run(world, statement_id)
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]

    entry = rows(
        world,
        "SELECT action, entity_type, new_values FROM audit_logs WHERE entity_id = %s",
        run_id,
    )
    assert len(entry) == 1, f"expected one audit row for the run, found {len(entry)}"
    action, entity_type, new_values = entry[0]
    assert action == "bank_statement.import_run_created"
    assert entity_type == "bank_statement_import_run"
    for column in ("run_number", "parser_version", "source_hash"):
        assert new_values.get(column), (
            f"the audit entry omits {column!r}. A reader asking why run 2 produced different rows "
            "than run 1 is asking a question these three answer."
        )


# --- SEC-IMPORT-001 ----------------------------------------------------------


def test_an_outgoing_account_cannot_receive_a_statement(world: dict[str, Any]) -> None:
    """`SEC-IMPORT-001`. Document 08 §8.1's "selected destination center account"."""

    sign_in_admin(world)
    response = upload_statement(world, bank_account_id=str(world["outgoing_account_id"]))
    assert response.status_code == 400, response.text
    assert "outgoing_source" in response.text


def test_a_statement_cannot_name_another_banks_account(world: dict[str, Any]) -> None:
    """`SEC-IMPORT-001`. The two selections §8.1 asks for must agree."""

    sign_in_admin(world)
    response = upload_statement(world, bank_account_id=str(world["other_bank_account_id"]))
    assert response.status_code == 400, response.text


def test_an_unscanned_file_cannot_be_imported(world: dict[str, Any]) -> None:
    """`SEC-IMPORT-001`. The parse opens this file, on a worker."""

    sign_in_admin(world)
    response = upload_statement(
        world, original_file_id=str(world["unscanned_file_object_id"])
    )
    assert response.status_code == 400, response.text
    assert "scan" in response.text


def test_half_a_date_range_is_refused(world: dict[str, Any]) -> None:
    """§8.1's range is optional; half of one says nothing about the period."""

    sign_in_admin(world)
    response = upload_statement(world, date_range_start="2026-08-01")
    assert response.status_code == 400, response.text


def test_a_draft_mapping_cannot_parse_a_statement(world: dict[str, Any]) -> None:
    """`SEC-IMPORT-001`. §8.1: ".xlsx for **approved** bank mappings"."""

    sign_in_admin(world)
    statement_id = a_statement(world)
    response = start_run(world, statement_id, bank_mapping_id=str(world["draft_mapping_id"]))
    assert response.status_code == 400, response.text
    assert "draft" in response.text


def test_an_export_mapping_cannot_parse_a_statement(world: dict[str, Any]) -> None:
    """`SEC-IMPORT-001`. DOC-CONFLICT-047's settled reading of `file_type`."""

    sign_in_admin(world)
    statement_id = a_statement(world)
    response = start_run(world, statement_id, bank_mapping_id=str(world["export_mapping_id"]))
    assert response.status_code == 400, response.text
    assert "outgoing_export" in response.text


def test_a_mapping_from_another_bank_version_cannot_parse_this_statement(
    world: dict[str, Any],
) -> None:
    """`SEC-IMPORT-001`. §8.2 parses "with exact BankProfileVersion and BankMapping".

    A mapping belonging to another version reads the bank's columns in the wrong places, and the
    failure would surface as rows that match nothing rather than as a configuration error.

    **This is not the recorded gap about mappings fitting a file, and the traceability gate is
    what settled that.** Naming the id here failed `test_no_recorded_gap_is_actually_covered`,
    which was right: that gap is document 08 §6.4's activation rule — a bank version may not be
    *activated* until its mappings parse representative fixtures — and this checks, at import
    time, that a mapping and a statement name the same version. Different moment, different
    subject. Closing that one needs a deterministic parser wired into activation, which is neither
    this slice nor, by itself, slice 4.
    """

    sign_in_admin(world)
    statement_id = a_statement(world)
    response = start_run(
        world, statement_id, bank_mapping_id=str(world["other_version_mapping_id"])
    )
    assert response.status_code == 400, response.text
    assert "exact version" in response.text


def test_no_trader_can_see_or_touch_a_statement(world: dict[str, Any]) -> None:
    """`SEC-IMPORT-001`. `permission_catalog.yaml` gives a trader none of the three permissions.

    Every route, not one: a surface where four routes are closed and the fifth is open is how a
    list endpoint becomes the leak. The reads are checked as well as the writes, because a
    statement carries the centre's account and one trader's transfer sits in it beside everybody
    else's.
    """

    sign_in_admin(world)
    statement_id = a_statement(world)

    sign_in_trader(world)
    client = world["client"]
    attempts = (
        client.get("/api/v1/bank-statements"),
        client.get(f"/api/v1/bank-statements/{statement_id}"),
        client.get(f"/api/v1/bank-statements/{statement_id}/import-runs"),
        client.post(
            "/api/v1/bank-statements",
            json={
                "bank_profile_version_id": str(world["our_version_id"]),
                "bank_account_id": str(world["incoming_account_id"]),
                "original_file_id": a_fresh_file(world),
            },
            headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
        ),
        client.post(
            f"/api/v1/bank-statements/{statement_id}/import-runs",
            json={"bank_mapping_id": str(world["statement_mapping_id"])},
            headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
        ),
    )
    for response in attempts:
        assert response.status_code == 403, (
            f"{response.request.method} {response.request.url.path} answered "
            f"{response.status_code}; a trader holds none of the three bank_statement permissions"
        )


def test_the_body_cannot_carry_a_run_number_or_a_parser(world: dict[str, Any]) -> None:
    """Enforcement by absence, and the schema is where it is enforced.

    A caller that could name the run number could aim a new run at an old one's slot; one that
    could name the parser version could label this run's rows as another parser's. Both are
    `extra="forbid"` rather than fields the command then refuses.
    """

    sign_in_admin(world)
    statement_id = a_statement(world)

    response = world["client"].post(
        f"/api/v1/bank-statements/{statement_id}/import-runs",
        json={
            "bank_mapping_id": str(world["statement_mapping_id"]),
            "run_number": 1,
            "parser_version": "9.9.9",
        },
        headers={**csrf(world), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 422, response.text


def test_the_runtime_cannot_rewrite_a_runs_provenance(world: dict[str, Any]) -> None:
    """`TRACE-IMPORT-001`, read as a privilege rather than inferred from behaviour.

    **The strongest form of `SVC-IMPORT-001`.** `run_number`, `parser_version`, `source_hash` and
    `bank_mapping_id` say which parse this was, what read it, which bytes it read and by what
    rules. A runtime that could update any of the four could turn run 1 into something
    indistinguishable from run 2, and no behavioural test can see that: a grant is a capability,
    and only a privilege query observes one. M9 slice 7B recorded that lesson and this is the same
    shape.
    """

    granted = rows(
        world,
        "SELECT DISTINCT column_name FROM information_schema.column_privileges "
        "WHERE table_name = 'bank_statement_import_runs' AND privilege_type = 'UPDATE' "
        "AND grantee = %s ORDER BY column_name",
        world["app_role"],
    )
    assert [row[0] for row in granted] == [
        "error_summary",
        "finished_at",
        "row_count",
        "started_at",
        "status",
    ], (
        f"the runtime may update {[row[0] for row in granted]} on an import run. Only its "
        "execution result moves; everything that says which parse this was must stay frozen."
    )

    on_the_file = rows(
        world,
        "SELECT DISTINCT column_name FROM information_schema.column_privileges "
        "WHERE table_name = 'bank_statement_files' AND privilege_type = 'UPDATE' "
        "AND grantee = %s ORDER BY column_name",
        world["app_role"],
    )
    assert [row[0] for row in on_the_file] == [
        "record_version",
        "status",
        "updated_at",
    ], (
        f"the runtime may update {[row[0] for row in on_the_file]} on a statement file. §10.4 "
        "calls it the immutable original, so its bank version, its account and its file id are "
        "not things a later request may change."
    )


def test_an_upload_is_uploaded_and_nothing_more(world: dict[str, Any]) -> None:
    """Document 06 §10.3 moves a file to `parsed` only when a run succeeds.

    The mirror of slice 2's `test_a_claim_confirms_nothing`: recording that a file arrived must not
    claim anything was read out of it.
    """

    sign_in_admin(world)
    response = upload_statement(world, original_file_id=a_fresh_file(world))
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "uploaded"

    stored = rows(
        world,
        "SELECT status FROM bank_statement_files WHERE id = %s",
        response.json()["id"],
    )
    assert stored[0][0] == "uploaded", (
        f"a freshly uploaded statement is {stored[0][0]!r}. Nothing has parsed it, and any other "
        "status would say something had."
    )
    assert (
        rows(
            world,
            "SELECT count(*) FROM bank_statement_import_runs WHERE bank_statement_file_id = %s",
            response.json()["id"],
        )[0][0]
        == 0
    ), "the upload started a parse. §8.2 makes the parse a separate step with its own mapping."
