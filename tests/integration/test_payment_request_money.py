"""What the trader typed, what it is worth, and what the server refuses to be told.

M5 slice 4. The conversion itself is M2's — `app/core/money.py` has held `to_rial`,
`Money` and a three-way consistency check since the persistence milestone. Until this
slice **nothing called any of it**: slice 3 took `amount_irr` as an integer and the
entered pair as optional extras, so a caller could hand the command a canonical figure
that did not follow from what was typed. That is the fifth time in this programme a
complete mechanism turned out to have no caller.

So these tests are as much about the wiring as the arithmetic. `500 TOMAN` and
`5000 IRR` must both store `5000`, and both must still say which one the trader typed.

**The validation matrix is not here.** Every invalid unit and malformed value moved to
`tests/backend/test_payment_amount_wire.py`, which runs the same forty cases in half a
second. Thirty-one cases here each provisioned a PostgreSQL and ran the whole Alembic
chain to test a Pydantic pattern, which timed out the CI job — the cost was the symptom
and the misplacement was the defect. What remains needs a database: that the conversion is
*stored*, that a refusal writes nothing, that the wire really carries strings, and one
representative refusal through the route so the wiring is still proved.

Covers: SVC-REQ-001, SVC-REQ-002, SVC-REQ-003, API-REQ-001.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PHONE = "+989120000201"
PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "X-CSRF-Token"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"
IBAN = "IR060120000000000000000001"


# Module-scoped, not function-scoped. Each case used to pay a bootstrap replay and a
# full `alembic upgrade head`, and the CI job timed out at forty-five minutes with roughly
# eighty-five such cases across these files.
#
# The trade is that these tests share a database and see each other's rows, so every
# aggregate query here is scoped to the row under test. That is not a tax the sharing
# imposes — an unscoped query claiming "submission wrote an audit row" was really claiming
# "some submission somewhere wrote one", and per-test isolation was hiding the difference.
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
        local_storage_root=tmp_path_factory.mktemp("storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    trader = uuid.uuid4()
    beneficiary = uuid.uuid4()
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        connection.execute(
            "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
            "approval_status) VALUES (%s, 'Trader', %s, 'active', 'approved')",
            (trader, PHONE),
        )
        connection.execute(
            "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
            "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
            (trader, PHONE, encoded),
        )
        connection.execute(
            "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
            "status, verification_status) VALUES (%s, %s, 'Ali', %s, %s, 'active', "
            "'not_checked')",
            (beneficiary, trader, IBAN, IBAN),
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://trader.localhost") as client:
        client.post(
            "/api/v1/auth/trader/login", json={"identifier": PHONE, "password": PASSWORD}
        )
        yield {
            "client": client,
            "trader": trader,
            "beneficiary": beneficiary,
            "owner_url": migrated.owner_url,
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _request_count(world: dict[str, Any]) -> int:
    """How many requests exist right now.

    Compared before and after rather than against zero. The world is module-scoped, so
    earlier tests in this file have legitimately created rows — and "the refusal wrote
    nothing" was always the claim, where "the table is empty" was only ever true by
    accident of isolation.
    """

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute("SELECT count(*) FROM payment_requests").fetchone()
    assert row is not None
    return int(row[0])


def draft(world: dict[str, Any], amount: dict[str, Any], **extra: Any) -> Any:
    client = world["client"]
    token = client.cookies.get(TRADER_CSRF_COOKIE)
    return client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary"]),
            "amount": amount,
            **extra,
        },
        headers={CSRF_HEADER: token},
    )


@pytest.mark.parametrize(
    ("value", "unit", "expected_irr"),
    [
        ("500", "TOMAN", "5000"),
        ("5000", "IRR", "5000"),
        ("1", "TOMAN", "10"),
        ("3440000000", "TOMAN", "34400000000"),
    ],
)
def test_the_server_converts_and_keeps_what_was_typed(
    world: dict[str, Any], value: str, unit: str, expected_irr: str
) -> None:
    """SVC-REQ-001.

    The first two rows are the same money entered two ways, which is the whole point:
    `amount_irr` must agree and `entered_amount` must differ. A revision that stored
    only the canonical figure could not tell them apart, and the difference is exactly
    what a dispute is about.

    The last row is document 05's own example value (`:1087`), so the arithmetic is
    checked against the number the specification chose rather than only against
    convenient ones.
    """

    created = draft(world, {"value": value, "unit": unit})
    assert created.status_code == 201, created.text
    revision = created.json()["revision"]

    assert revision["amount_irr"] == expected_irr
    assert revision["entered_amount"] == {"value": value, "unit": unit}


def test_two_entries_of_the_same_money_differ_only_in_provenance(
    world: dict[str, Any],
) -> None:
    """SVC-REQ-001, stated as one assertion rather than two rows.

    Read back from the database, because this is a claim about what was stored.
    """

    toman = draft(world, {"value": "500", "unit": "TOMAN"}).json()["revision"]
    rial = draft(world, {"value": "5000", "unit": "IRR"}).json()["revision"]

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        rows = connection.execute(
            "SELECT id, amount_irr, entered_amount_value, entered_amount_unit "
            "FROM payment_request_revisions WHERE id = ANY(%s) ORDER BY created_at",
            ([toman["id"], rial["id"]],),
        ).fetchall()

    assert len(rows) == 2
    assert {row[1] for row in rows} == {5000}, "the canonical amounts disagree"
    assert {(row[2], row[3]) for row in rows} == {(500, "TOMAN"), (5000, "IRR")}


def test_a_client_supplied_amount_irr_is_verified_not_trusted(world: dict[str, Any]) -> None:
    """SVC-REQ-002.

    Document 05's create example carries all three parts (`:1085-1091`), so sending
    `amount_irr` must work — and must be *checked*. A figure that does not follow from
    the entered pair is refused rather than reconciled, because reconciling means
    choosing which number to believe and both choices move money.
    """

    agreeing = draft(
        world, {"value": "500", "unit": "TOMAN", "amount_irr": "5000"}
    )
    assert agreeing.status_code == 201, agreeing.text
    assert agreeing.json()["revision"]["amount_irr"] == "5000"

    # Off by exactly the conversion factor: the mistake a client makes by converting
    # twice, or not at all.
    disagreeing = draft(world, {"value": "500", "unit": "TOMAN", "amount_irr": "500"})
    assert disagreeing.status_code == 400, disagreeing.text
    assert disagreeing.json()["error"]["code"] == "AMOUNT_UNIT_MISMATCH"


def test_a_refused_amount_writes_nothing(world: dict[str, Any]) -> None:
    """SVC-REQ-002.

    The refusal has to happen before the insert. A route that answered 400 after
    writing would look identical from outside and would leave a revision whose
    canonical figure nobody can justify.
    """

    before = _request_count(world)
    draft(world, {"value": "500", "unit": "TOMAN", "amount_irr": "500"})

    assert _request_count(world) == before, "the refused amount wrote a row anyway"


def test_every_amount_in_the_response_is_a_string(world: dict[str, Any]) -> None:
    """API-REQ-001, from the server's side.

    Asserted against the **raw JSON text**, not the parsed body. `json.loads` would
    turn `34400000000` into a Python int and the assertion would pass on a response
    that had emitted a number — the precision loss this rule exists to prevent
    happens in the client's parser, not in ours.

    The value is above 2^32 and chosen from document 05's own example, so a client
    using a 32-bit integer or a float would visibly mangle it.
    """

    created = draft(world, {"value": "3440000000", "unit": "TOMAN"})
    assert created.status_code == 201

    raw = created.text
    assert '"amount_irr":"34400000000"' in raw.replace(" ", ""), raw
    assert '"value":"3440000000"' in raw.replace(" ", ""), raw

    # And nothing anywhere in the body renders a monetary field unquoted.
    body = json.loads(raw)
    revision = body["revision"]
    for field in ("amount_irr",):
        assert isinstance(revision[field], str), f"{field} is {type(revision[field])}"
    assert isinstance(revision["entered_amount"]["value"], str)


def test_the_route_refuses_an_invalid_unit(world: dict[str, Any]) -> None:
    """One refusal through the real route, standing for the whole matrix.

    `tests/backend/test_payment_amount_wire.py` owns the matrix — every invalid unit and
    every malformed value — because those are claims about a Pydantic pattern and `_money`,
    and a test that needs no database should not have one.

    What a unit test cannot say is that the validator is *wired to the endpoint*. This is
    that claim, and one case is enough for it: if the wiring were missing, no case would
    refuse.
    """

    refused = draft(world, {"value": "500", "unit": "RIAL"})
    assert refused.status_code in {400, 422}, refused.text


def test_slice_threes_flat_shape_still_works(world: dict[str, Any]) -> None:
    """The compatibility path, which exists because of a gate rather than a requirement.

    Making `amount` required and dropping the flat fields is a breaking request change.
    The oasdiff gate refuses one and its waiver is an unresolved `TODO(governance)` in
    `.github/workflows/m1-verify.yml:182`, left open through M2 and M3 — and the M2 plan
    records the strategy that follows: while no waiver exists, changes stay additive.

    So the flat trio is still accepted, and it must go through the same conversion. A
    compatibility path that skipped the checks would be the shape an attacker uses.
    """

    client = world["client"]
    token = client.cookies.get(TRADER_CSRF_COOKIE)

    created = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary"]),
            "entered_amount_value": "500",
            "entered_amount_unit": "TOMAN",
        },
        headers={CSRF_HEADER: token},
    )
    assert created.status_code == 201, created.text
    revision = created.json()["revision"]

    assert revision["amount_irr"] == "5000"
    assert revision["entered_amount"] == {"value": "500", "unit": "TOMAN"}
    # And the deprecated response fields carry the same values, from the same source.
    assert revision["entered_amount_value"] == "500"
    assert revision["entered_amount_unit"] == "TOMAN"


