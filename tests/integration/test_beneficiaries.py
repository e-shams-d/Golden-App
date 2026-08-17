"""The beneficiary API against two real traders, a real admin and a real database.

M5 slice 2. Two traders exist in this fixture for the reason
`test_trader_isolation.py` records: every isolation claim needs two parties to mean
anything, and M2's primary-contact defect survived because no test ever created a
second trader.

**The duplicate-warning tests are the ones to read first.** Three documents say a
duplicate must warn rather than refuse, and the natural implementation refuses —
so `test_a_duplicate_iban_is_created_and_warned_about` asserts a `201` and then
asserts the row is really there, because a warning attached to a rejection would
satisfy a shallower test.

Covers: SVC-BEN-001, SVC-BEN-002, SEC-BEN-001, AUD-BEN-001, SEC-IDOR-003.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

TRADER_A_PHONE = "+989120000011"
TRADER_B_PHONE = "+989120000012"
PASSWORD = "correct-horse-battery-staple"

CSRF_HEADER = "X-CSRF-Token"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"

IBAN_ONE = "IR060120000000000000000001"
IBAN_TWO = "IR060120000000000000000002"

# What a trader actually types in a Persian interface: Persian digits, and the
# four-character grouping banks print. It must normalise to `IBAN_ONE`, or the
# duplicate warning misses the duplicate it exists to find.
IBAN_ONE_AS_TYPED = "IR۰۶ ۰۱۲۰ ۰۰۰۰ ۰۰۰۰ ۰۰۰۰ ۰۰۰۰ ۰۱"


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
    """Two traders, one admin with the beneficiary permissions, one without."""

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

    trader_a, trader_b = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for trader_id, name, phone in (
            (trader_a, "Trader A", TRADER_A_PHONE),
            (trader_b, "Trader B", TRADER_B_PHONE),
        ):
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
                (trader_id, name, phone),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, %s, %s, 'active', TRUE)",
                (trader_id, phone, f"{name} Contact", encoded),
            )

        # `staff_granted` holds the beneficiary permissions through `accountant`;
        # `staff_bare` holds a session and nothing else. The second is what makes
        # the permission negatives mean something: without it, a 403 could come
        # from not being signed in.
        for username in ("staff_granted", "staff_bare"):
            connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active')",
                (username, f"{username} User", encoded),
            )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = 'staff_granted' AND r.code = 'accountant'"
        )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://trader.localhost") as client:
        yield {
            "client": client,
            "trader_a": trader_a,
            "trader_b": trader_b,
            "owner_url": migrated.owner_url,
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in_trader(client: Any, phone: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": phone, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def sign_in_admin(client: Any, username: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(client: Any) -> dict[str, str]:
    """The double-submit token for whichever audience is signed in.

    Every mutating request needs it, and a missing one is refused with the same
    `FORBIDDEN` / "Permission denied." envelope a missing grant produces. That
    collision is why the permission negatives below are written to fail if CSRF
    were the real cause — see `test_an_admin_without_the_permission_is_refused`.
    """

    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def create(client: Any, iban: str, name: str = "Ali Example", **extra: Any) -> Any:
    return client.post(
        "/api/v1/beneficiaries",
        json={"full_name": name, "iban": iban, **extra},
        headers=csrf(client),
    )


def test_a_trader_creates_a_beneficiary_and_reads_it_back(world: dict[str, Any]) -> None:
    """SVC-BEN-001, the ordinary path.

    The trader id is never sent and is never accepted from the body: it comes from
    the session, so the response naming trader A is the guard working rather than
    the request being obeyed.
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)

    created = create(client, IBAN_ONE)
    assert created.status_code == 201, created.text
    body = created.json()

    assert body["beneficiary"]["trader_id"] == str(world["trader_a"])
    assert body["beneficiary"]["status"] == "active"
    assert body["beneficiary"]["verification_status"] == "not_checked"
    assert body["duplicate_warnings"] == []

    listed = client.get("/api/v1/beneficiaries")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [body["beneficiary"]["id"]]


def test_a_duplicate_iban_is_created_and_warned_about(world: dict[str, Any]) -> None:
    """SVC-BEN-001, and the point of the whole slice.

    `15_Agent_Implementation_Plan.md:801`, `04_Database_Schema.md:527` and
    `06_Workflows_and_State_Machines.md:299` all say the warning does not block.
    So this asserts three things a refusal would fail: the status is `201`, the
    warning names the earlier row, and **both** rows are in the trader's list
    afterwards.

    The last one matters on its own. A route that warned and then quietly declined
    to insert would return a plausible body and pass any test that only read it.
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)

    first = create(client, IBAN_ONE, name="Ali Example")
    assert first.status_code == 201
    first_id = first.json()["beneficiary"]["id"]

    second = create(client, IBAN_ONE, name="Someone Else Entirely")
    assert second.status_code == 201, "a duplicate IBAN must be created, not refused"

    warnings = second.json()["duplicate_warnings"]
    assert [w["beneficiary_id"] for w in warnings] == [first_id]
    assert warnings[0]["matched_on"] == "iban"
    assert warnings[0]["full_name"] == "Ali Example"

    listed = client.get("/api/v1/beneficiaries").json()["items"]
    assert len(listed) == 2, "the duplicate was warned about and then not stored"


def test_a_persian_digit_iban_is_recognised_as_the_same_account(
    world: dict[str, Any],
) -> None:
    """SVC-BEN-001.

    The normalisation is what makes the warning true. An Iranian trader typing
    into a Persian interface produces Persian digits and the grouping their bank
    prints; storing that verbatim would make two spellings of one account, and the
    duplicate check would then find nothing while the trader stared at two
    identical-looking rows.
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)

    assert create(client, IBAN_ONE).status_code == 201
    second = create(client, IBAN_ONE_AS_TYPED, name="Same Account Retyped")

    assert second.status_code == 201
    assert second.json()["beneficiary"]["iban"] == IBAN_ONE_AS_TYPED, (
        "the display field must keep what was typed"
    )
    assert [w["matched_on"] for w in second.json()["duplicate_warnings"]] == ["iban"]


def test_a_matching_name_warns_even_when_the_iban_differs(world: dict[str, Any]) -> None:
    """SVC-BEN-001.

    Two accounts for one person is the case document 04 names as legitimate. The
    warning still fires — it is advice — and `matched_on` says which of the two
    facts matched, so a screen can word it correctly.
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)

    assert create(client, IBAN_ONE, name="Ali Example").status_code == 201
    second = create(client, IBAN_TWO, name="ALI  EXAMPLE")

    assert second.status_code == 201
    assert [w["matched_on"] for w in second.json()["duplicate_warnings"]] == ["name"]


def test_another_traders_beneficiary_does_not_produce_a_warning(
    world: dict[str, Any],
) -> None:
    """SEC-BEN-001, and the subtle half of it.

    Trader B creating the IBAN trader A already has must get **no** warning. A
    warning here would leak that somebody else on the platform banks with that
    account — the isolation defeated by a helpful message rather than by a missing
    guard, which no ownership test on a read endpoint would catch.
    """

    client = world["client"]

    sign_in_trader(client, TRADER_A_PHONE)
    assert create(client, IBAN_ONE, name="Ali Example").status_code == 201

    sign_in_trader(client, TRADER_B_PHONE)
    created = create(client, IBAN_ONE, name="Ali Example")

    assert created.status_code == 201
    assert created.json()["duplicate_warnings"] == [], (
        "trader B was told about trader A's beneficiary"
    )


def test_a_trader_reads_only_its_own_beneficiaries(world: dict[str, Any]) -> None:
    """SEC-BEN-001 and SEC-IDOR-003, the mandatory case
    `14_Testing_QA_Acceptance.md:1277` calls "Trader A reads Trader B beneficiary".

    Deferred to M5 by `test_trader_isolation.py`'s ledger since slice 10 of M3.
    This is the slice that owes it.

    Both directions are asserted: A cannot reach B's row, and A's list is A's own
    rather than empty. A list endpoint returning nothing to everybody would satisfy
    the first half by accident.
    """

    client = world["client"]

    sign_in_trader(client, TRADER_B_PHONE)
    b_id = create(client, IBAN_TWO, name="Trader B Recipient").json()["beneficiary"]["id"]

    sign_in_trader(client, TRADER_A_PHONE)
    a_id = create(client, IBAN_ONE, name="Trader A Recipient").json()["beneficiary"]["id"]

    assert client.get(f"/api/v1/beneficiaries/{b_id}").status_code == 404
    assert client.get(f"/api/v1/beneficiaries/{a_id}").status_code == 200

    listed = client.get("/api/v1/beneficiaries").json()["items"]
    assert [item["id"] for item in listed] == [a_id]


def test_a_missing_id_and_another_traders_id_are_indistinguishable(
    world: dict[str, Any],
) -> None:
    """SEC-BEN-001.

    The pattern M4 slice 5 established for files. A `403` on the second would
    confirm the id names a real beneficiary belonging to somebody, turning the
    endpoint into a membership oracle over other traders' address books.

    Status **and** body are compared: two 404s with different messages leak the
    same fact more quietly.
    """

    client = world["client"]

    sign_in_trader(client, TRADER_B_PHONE)
    b_id = create(client, IBAN_TWO).json()["beneficiary"]["id"]

    sign_in_trader(client, TRADER_A_PHONE)
    theirs = client.get(f"/api/v1/beneficiaries/{b_id}")
    absent = client.get(f"/api/v1/beneficiaries/{uuid.uuid4()}")

    assert theirs.status_code == absent.status_code == 404

    # Everything but `request_id`, which is per-request by design and is the one
    # field that must differ. Comparing the whole body would compare that too and
    # the test could never pass; dropping the comparison entirely would let the two
    # messages diverge, which leaks the same fact more quietly than a 403 does.
    assert _without_request_id(theirs.json()) == _without_request_id(absent.json())


def _without_request_id(envelope: dict[str, Any]) -> dict[str, Any]:
    error = {key: value for key, value in envelope["error"].items() if key != "request_id"}
    return {**envelope, "error": error}


def test_a_trader_cannot_patch_another_traders_beneficiary(world: dict[str, Any]) -> None:
    """SEC-BEN-001, on the write path.

    A read guard that a write path skipped would be the whole isolation, present
    and bypassable.
    """

    client = world["client"]

    sign_in_trader(client, TRADER_B_PHONE)
    created = create(client, IBAN_TWO).json()["beneficiary"]
    version = created["record_version"]

    sign_in_trader(client, TRADER_A_PHONE)
    patched = client.patch(
        f"/api/v1/beneficiaries/{created['id']}",
        json={"full_name": "Renamed By A"},
        headers={**csrf(client), "If-Match": f'"rv-{version}"'},
    )
    assert patched.status_code == 404

    deactivated = client.post(
        f"/api/v1/beneficiaries/{created['id']}/deactivate",
        json={},
        headers={**csrf(client), "If-Match": f'"rv-{version}"'},
    )
    assert deactivated.status_code == 404

    sign_in_trader(client, TRADER_B_PHONE)
    after = client.get(f"/api/v1/beneficiaries/{created['id']}").json()
    assert after["full_name"] == created["full_name"]
    assert after["status"] == "active"


def test_editing_a_beneficiary_requires_a_current_if_match(world: dict[str, Any]) -> None:
    """`05_API_Specification.md:940`. The stale-tab case."""

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)
    created = create(client, IBAN_ONE).json()["beneficiary"]

    without = client.patch(
        f"/api/v1/beneficiaries/{created['id']}",
        json={"full_name": "New Name"},
        headers=csrf(client),
    )
    assert without.status_code == 428

    stale = client.patch(
        f"/api/v1/beneficiaries/{created['id']}",
        json={"full_name": "New Name"},
        headers={**csrf(client), "If-Match": '"rv-99"'},
    )
    assert stale.status_code == 412

    current = client.patch(
        f"/api/v1/beneficiaries/{created['id']}",
        json={"full_name": "New Name"},
        headers={**csrf(client), "If-Match": f'"rv-{created["record_version"]}"'},
    )
    assert current.status_code == 200
    assert current.json()["full_name"] == "New Name"


def test_deactivation_keeps_the_row(world: dict[str, Any]) -> None:
    """SVC-BEN-002.

    Retiring is a status change, and the row stays readable. A request created
    later will snapshot its beneficiary, and the row is what a dispute is read
    against — so "deactivate" deleting anything would remove the subject of
    evidence that has not been written yet.
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)
    created = create(client, IBAN_ONE).json()["beneficiary"]

    response = client.post(
        f"/api/v1/beneficiaries/{created['id']}/deactivate",
        json={"reason": "closed the account"},
        headers={**csrf(client), "If-Match": f'"rv-{created["record_version"]}"'},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "inactive"

    still_there = client.get(f"/api/v1/beneficiaries/{created['id']}")
    assert still_there.status_code == 200
    assert still_there.json()["status"] == "inactive"

    listed = client.get("/api/v1/beneficiaries").json()["items"]
    assert [item["id"] for item in listed] == [created["id"]], (
        "a retired beneficiary vanished from the list, which is deletion by another name"
    )


def test_a_retired_beneficiary_still_warns_on_re_entry(world: dict[str, Any]) -> None:
    """SVC-BEN-002.

    A trader who retired a beneficiary and is typing it again wants to be told the
    old one is there. Excluding retired rows from the lookup would produce exactly
    the second copy the warning exists to prevent.
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)
    created = create(client, IBAN_ONE).json()["beneficiary"]
    client.post(
        f"/api/v1/beneficiaries/{created['id']}/deactivate",
        json={},
        headers={**csrf(client), "If-Match": f'"rv-{created["record_version"]}"'},
    )

    again = create(client, IBAN_ONE, name="Same Account Again")
    assert again.status_code == 201
    assert [w["beneficiary_id"] for w in again.json()["duplicate_warnings"]] == [
        created["id"]
    ]


@pytest.mark.parametrize(
    ("method", "path_suffix", "body"),
    [
        ("get", "", None),
        ("post", "", {"full_name": "X", "iban": IBAN_ONE}),
    ],
)
def test_an_admin_without_the_permission_is_refused(
    world: dict[str, Any], method: str, path_suffix: str, body: dict[str, Any] | None
) -> None:
    """The permission negative for the collection routes.

    `staff_bare` holds a real session and no beneficiary permission, which is what
    makes the `403` mean "not permitted" rather than "not signed in".

    **The CSRF token is sent, and that is the load-bearing detail.** A missing one
    is refused with the identical `FORBIDDEN` / "Permission denied." envelope, so a
    version of this test that omitted it would assert 403, pass, and prove nothing
    about permissions at all. The guard-the-guard is the second half: the same call
    with `staff_granted` must succeed, so the refusal is demonstrably about the
    grant rather than about anything else in the request.
    """

    client = world["client"]
    if body is not None:
        # An internal actor must name the trader it acts for; the field is read only
        # on that path (`05_API_Specification.md:947`), and it must be a real trader
        # or the foreign key would refuse the granted call for an unrelated reason.
        body = {**body, "trader_id": str(world["trader_a"])}

    sign_in_admin(client, "staff_bare")
    refused = _call(client, method, path_suffix, body)
    assert refused.status_code == 403, refused.text

    sign_in_admin(client, "staff_granted")
    allowed = _call(client, method, path_suffix, body)
    assert allowed.status_code != 403, (
        f"the permitted admin was refused too ({allowed.status_code}), so the 403 above "
        f"was not about the permission: {allowed.text}"
    )


def _call(client: Any, method: str, path_suffix: str, body: dict[str, Any] | None) -> Any:
    call = getattr(client, method)
    path = f"/api/v1/beneficiaries{path_suffix}"
    if body is None:
        return call(path)
    return call(path, json=body, headers=csrf(client))


def test_an_admin_without_the_permission_is_refused_on_one_beneficiary(
    world: dict[str, Any],
) -> None:
    """The permission negative for the item routes.

    Asserted as `403` rather than `404`, and that is the deliberate difference from
    the trader case above. A trader must not learn the id is real; an internal
    caller already knows the resource class exists and is being told they lack a
    grant, which is the answer that sends them to an administrator rather than
    looking for a typo.

    The `GET` here is the assertion that cannot be confused with anything else: it
    carries no CSRF token because it needs none, so its `403` can only be the
    permission.
    """

    client = world["client"]

    sign_in_trader(client, TRADER_A_PHONE)
    created = create(client, IBAN_ONE).json()["beneficiary"]

    sign_in_admin(client, "staff_bare")
    header = {**csrf(client), "If-Match": f'"rv-{created["record_version"]}"'}

    assert client.get(f"/api/v1/beneficiaries/{created['id']}").status_code == 403
    assert (
        client.patch(
            f"/api/v1/beneficiaries/{created['id']}",
            json={"full_name": "N"},
            headers=header,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/beneficiaries/{created['id']}/deactivate", json={}, headers=header
        ).status_code
        == 403
    )


def test_a_permitted_admin_reaches_every_trader_and_may_filter(
    world: dict[str, Any],
) -> None:
    """The other side of the permission negative.

    Without this, `403` for everyone would pass the test above — the refusal has to
    be about the grant, so somebody holding it must get through.
    """

    client = world["client"]

    sign_in_trader(client, TRADER_A_PHONE)
    create(client, IBAN_ONE, name="A Recipient")
    sign_in_trader(client, TRADER_B_PHONE)
    create(client, IBAN_TWO, name="B Recipient")

    sign_in_admin(client, "staff_granted")
    everything = client.get("/api/v1/beneficiaries")
    assert everything.status_code == 200
    assert len(everything.json()["items"]) == 2

    filtered = client.get(f"/api/v1/beneficiaries?trader_id={world['trader_a']}")
    assert [item["full_name"] for item in filtered.json()["items"]] == ["A Recipient"]


def test_a_trader_cannot_create_a_beneficiary_under_another_trader(
    world: dict[str, Any],
) -> None:
    """SEC-BEN-001, and `14_Testing_QA_Acceptance.md:1280` on the create path.

    **This test exists because a negative control found it missing.** The create
    body carries an optional `trader_id` for internal actors
    (`05_API_Specification.md:947`), and it is on the same path a trader posts to.
    Rewriting the route to prefer the body over the session — a one-line change
    that looks like sensible precedence — left every other test in this file
    passing, because none of them sends the field.

    The refusal is that the value is not read on the trader path, so a trader
    sending trader B's id gets a beneficiary of their own. Asserted from both ends:
    the response says trader A, and trader B's list stays empty.
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)

    created = client.post(
        "/api/v1/beneficiaries",
        json={
            "full_name": "Ali Example",
            "iban": IBAN_ONE,
            "trader_id": str(world["trader_b"]),
        },
        headers=csrf(client),
    )
    assert created.status_code == 201, created.text
    assert created.json()["beneficiary"]["trader_id"] == str(world["trader_a"]), (
        "the submitted trader_id was honoured; a trader created a row under another trader"
    )

    sign_in_trader(client, TRADER_B_PHONE)
    assert client.get("/api/v1/beneficiaries").json()["items"] == []


def test_a_trader_cannot_patch_a_beneficiary_onto_another_trader(
    world: dict[str, Any],
) -> None:
    """SEC-BEN-001, the same hole on the update path.

    `UpdateBeneficiaryRequest` has no `trader_id` field at all and `extra="forbid"`
    refuses one, so this asserts the absence rather than a filter — the mandatory
    case is "have no argument to submit it to", not "validate what was submitted".
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)
    created = create(client, IBAN_ONE).json()["beneficiary"]

    response = client.patch(
        f"/api/v1/beneficiaries/{created['id']}",
        json={"full_name": "Renamed", "trader_id": str(world["trader_b"])},
        headers={**csrf(client), "If-Match": f'"rv-{created["record_version"]}"'},
    )
    assert response.status_code == 422, (
        "an unexpected trader_id was accepted or ignored; it must be refused"
    )


def test_a_trader_cannot_use_the_filter_to_read_another_trader(
    world: dict[str, Any],
) -> None:
    """SEC-BEN-001.

    The query parameter exists for internal callers (`05_API_Specification.md:938`)
    and is on the same path a trader uses. A trader passing another trader's id
    gets their own list back, because the trader branch never consults it — the
    defence is that the value is not read, not that it is validated.
    """

    client = world["client"]

    sign_in_trader(client, TRADER_B_PHONE)
    create(client, IBAN_TWO, name="B Recipient")

    sign_in_trader(client, TRADER_A_PHONE)
    create(client, IBAN_ONE, name="A Recipient")

    listed = client.get(f"/api/v1/beneficiaries?trader_id={world['trader_b']}")
    assert listed.status_code == 200
    assert [item["full_name"] for item in listed.json()["items"]] == ["A Recipient"]


def test_each_command_writes_its_audit_row_in_the_same_transaction(
    world: dict[str, Any],
) -> None:
    """AUD-BEN-001.

    Read from `audit_logs` with a separate connection after the request returned,
    so what is asserted is what committed rather than what the session held.
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)

    created = create(client, IBAN_ONE).json()["beneficiary"]
    client.patch(
        f"/api/v1/beneficiaries/{created['id']}",
        json={"full_name": "Corrected Name"},
        headers={**csrf(client), "If-Match": f'"rv-{created["record_version"]}"'},
    )
    current = client.get(f"/api/v1/beneficiaries/{created['id']}").json()
    client.post(
        f"/api/v1/beneficiaries/{created['id']}/deactivate",
        json={"reason": "closed"},
        headers={**csrf(client), "If-Match": f'"rv-{current["record_version"]}"'},
    )

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        rows = connection.execute(
            "SELECT action, outcome, entity_type, entity_id FROM audit_logs "
            "WHERE entity_type = 'beneficiary' ORDER BY occurred_at"
        ).fetchall()

    # In the order they happened, which is the order the trail has to read in. The
    # three requests are separate transactions, so `occurred_at` orders them
    # unambiguously and no tie-break is needed.
    assert [row[0] for row in rows] == [
        "beneficiary.created",
        "beneficiary.updated",
        "beneficiary.deactivated",
    ], f"actions recorded: {[row[0] for row in rows]}"
    assert {row[1] for row in rows} == {"success"}
    assert {str(row[3]) for row in rows} == {created["id"]}


def test_the_duplicate_warning_is_recorded_not_only_returned(
    world: dict[str, Any],
) -> None:
    """AUD-BEN-001.

    A trader who created a duplicate deliberately and one who did it by accident
    look identical in the data afterwards. The audit row is where "they were shown
    the warning" is written down, and without it the platform could not later say
    whether anybody was told.
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)

    first = create(client, IBAN_ONE).json()["beneficiary"]["id"]
    create(client, IBAN_ONE, name="Second Copy")

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        rows = connection.execute(
            "SELECT metadata FROM audit_logs WHERE action = 'beneficiary.created' "
            "ORDER BY occurred_at"
        ).fetchall()

    assert rows[0][0]["duplicate_warnings"] == []
    assert rows[1][0]["duplicate_warnings"] == [first]


def test_an_invalid_iban_is_refused(world: dict[str, Any]) -> None:
    """The one thing that *is* a refusal.

    A duplicate is legitimate; a malformed IBAN is not payable at all. Refusing it
    at creation is the difference between a warning and an error, and having both
    in the same slice is what keeps the distinction visible.
    """

    client = world["client"]
    sign_in_trader(client, TRADER_A_PHONE)

    response = create(client, "NL91ABNA0417164300")
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"
