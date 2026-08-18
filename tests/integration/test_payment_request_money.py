"""What the trader typed, what it is worth, and what the server refuses to be told.

M5 slice 4. The conversion itself is M2's — `app/core/money.py` has held `to_rial`,
`Money` and a three-way consistency check since the persistence milestone. Until this
slice **nothing called any of it**: slice 3 took `amount_irr` as an integer and the
entered pair as optional extras, so a caller could hand the command a canonical figure
that did not follow from what was typed. That is the fifth time in this programme a
complete mechanism turned out to have no caller.

So these tests are as much about the wiring as the arithmetic. `500 TOMAN` and
`5000 IRR` must both store `5000`, and both must still say which one the trader typed.

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


@pytest.fixture
def migrated(provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return provisioned_database


@pytest.fixture
def world(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[dict[str, Any]]:
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
        local_storage_root=tmp_path / "storage",
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

    draft(world, {"value": "500", "unit": "TOMAN", "amount_irr": "500"})

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        count = connection.execute("SELECT count(*) FROM payment_requests").fetchone()

    assert count is not None and count[0] == 0


@pytest.mark.parametrize(
    "unit", ["IRR ", "irr", "RIAL", "USD", "TOMANS", "", "TOMAN\n"]
)
def test_an_invalid_unit_is_refused(world: dict[str, Any], unit: str) -> None:
    """SVC-REQ-002.

    `irr` lowercase is in the list deliberately. Phase 1A supports exactly two units
    and accepting a case variant would mean the stored `entered_amount_unit` has more
    than one spelling — which the column's CHECK would then refuse at the insert,
    turning a client's typo into a 500 instead of a 400.
    """

    refused = draft(world, {"value": "500", "unit": unit})
    assert refused.status_code in {400, 422}, refused.text


@pytest.mark.parametrize(
    "value", ["0", "-500", "5.5", "1e9", "1,000", " 500", "500 ", "abc", ""]
)
def test_a_value_that_is_not_a_plain_integer_is_refused(
    world: dict[str, Any], value: str
) -> None:
    """SVC-REQ-002, and the reason `parse_integer_string` is strict.

    `"1.25e9"` and `"1,250,000,000"` are both plausible typos for values that differ by
    orders of magnitude, and `"0"` is not a payment. Refusing rather than coercing is
    what keeps a formatting accident from becoming a different amount.
    """

    refused = draft(world, {"value": value, "unit": "TOMAN"})
    assert refused.status_code in {400, 422}, refused.text


def test_a_json_number_amount_is_refused(world: dict[str, Any]) -> None:
    """API-REQ-001, from the client's side.

    The money contract's rule 8 is that API monetary values are base-10 integer
    strings, and rule 9 forbids JavaScript Number for financial amounts. A client that
    sends `500` instead of `"500"` is using the type the contract forbids, and it is
    refused rather than coerced — coercion would make the forbidden form work, and
    then it would be used.
    """

    client = world["client"]
    token = client.cookies.get(TRADER_CSRF_COOKIE)
    refused = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary"]),
            "amount": {"value": 500, "unit": "TOMAN"},
        },
        headers={CSRF_HEADER: token},
    )

    assert refused.status_code == 422, refused.text


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


def test_no_conversion_factor_is_accepted_from_the_client(world: dict[str, Any]) -> None:
    """SVC-REQ-003.

    `RIAL_PER_TOMAN` is a constant in one module and the API has no field through
    which a caller could supply another. Asserted structurally — `extra="forbid"`
    refuses the field rather than ignoring it — because a factor that could be
    submitted is one that could be submitted as 1 and make a TOMAN amount ten times
    too small.
    """

    client = world["client"]
    token = client.cookies.get(TRADER_CSRF_COOKIE)

    for field, payload in (
        ("rial_per_toman", {"value": "500", "unit": "TOMAN", "rial_per_toman": "1"}),
        ("factor", {"value": "500", "unit": "TOMAN", "factor": "1"}),
        ("rate", {"value": "500", "unit": "TOMAN", "rate": "1"}),
    ):
        refused = client.post(
            "/api/v1/payment-requests",
            json={"beneficiary_id": str(world["beneficiary"]), "amount": payload},
            headers={CSRF_HEADER: token},
        )
        assert refused.status_code == 422, f"{field} was accepted or ignored: {refused.text}"


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


def test_the_flat_path_verifies_a_supplied_amount_irr_too(world: dict[str, Any]) -> None:
    """The compatibility path is not a way around the three-way check."""

    client = world["client"]
    token = client.cookies.get(TRADER_CSRF_COOKIE)

    refused = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary"]),
            "entered_amount_value": "500",
            "entered_amount_unit": "TOMAN",
            "amount_irr": "500",
        },
        headers={CSRF_HEADER: token},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "AMOUNT_UNIT_MISMATCH"


def test_sending_both_shapes_is_refused(world: dict[str, Any]) -> None:
    """Refused rather than resolved by precedence.

    A rule about which shape wins is a rule somebody has to know, and a caller sending
    `amount` alongside a contradicting `entered_amount_value` has already lost track of
    what they are asking for. Answering with one of them would pick a number on their
    behalf.
    """

    client = world["client"]
    token = client.cookies.get(TRADER_CSRF_COOKIE)

    refused = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiary"]),
            "amount": {"value": "500", "unit": "TOMAN"},
            "entered_amount_value": "900",
            "entered_amount_unit": "TOMAN",
        },
        headers={CSRF_HEADER: token},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "AMOUNT_UNIT_MISMATCH"


def test_an_amount_is_required_in_one_shape_or_the_other(world: dict[str, Any]) -> None:
    """`amount` is optional in the schema and not optional in effect.

    Making it schema-optional was forced by the additive rule; it must not become a way
    to create a request with no amount at all.
    """

    client = world["client"]
    token = client.cookies.get(TRADER_CSRF_COOKIE)

    refused = client.post(
        "/api/v1/payment-requests",
        json={"beneficiary_id": str(world["beneficiary"])},
        headers={CSRF_HEADER: token},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "AMOUNT_UNIT_MISMATCH"


def test_the_conversion_is_not_applied_twice(world: dict[str, Any]) -> None:
    """SVC-REQ-001, the arithmetic error `to_rial`'s docstring names.

    "A second implementation of this is how a factor of ten gets applied twice." An
    `IRR` entry must be stored unchanged — if the unit branch were wrong, a rial
    amount would be multiplied by ten and nothing about the response would look odd.
    """

    created = draft(world, {"value": "5000", "unit": "IRR"})
    assert created.json()["revision"]["amount_irr"] == "5000"

    doubled = draft(world, {"value": "500", "unit": "TOMAN"})
    assert doubled.json()["revision"]["amount_irr"] == "5000"
    assert doubled.json()["revision"]["amount_irr"] != "50000"
