"""A correction adds a revision, and the previous one does not move.

M5 slice 5. This is the milestone's central property, and the test that matters most is
`test_the_previous_revision_is_byte_identical_afterwards`: it reads every column of
revision *n* before and after a correction and requires them equal. Not "the amount is
unchanged" — every column, including `content_hash` and `created_at`, because a
revision that could be edited in any field is not evidence.

Covers: SVC-REV-001, SVC-REV-002, SVC-REV-003, SVC-REV-004, CON-REQ-002.
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

PASSWORD = "correct-horse-battery-staple"
CSRF_HEADER = "X-CSRF-Token"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"

TRADERS: dict[str, str] = {"ok": "+989120000301", "other": "+989120000302"}
IBAN_ONE = "IR060120000000000000000001"
IBAN_TWO = "IR060120000000000000000002"

REVISION_COLUMNS = (
    "id",
    "payment_request_id",
    "revision_number",
    "beneficiary_id",
    "beneficiary_name_snapshot",
    "beneficiary_iban_snapshot",
    "beneficiary_national_id_snapshot",
    "amount_irr",
    "entered_amount_value",
    "entered_amount_unit",
    "description",
    "source_attachment_file_id",
    "revision_reason",
    "content_hash",
    "created_by_actor_type",
    "created_by_actor_id",
    "created_at",
    "superseded_at",
)


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

    traders = {name: uuid.uuid4() for name in TRADERS}
    # Two beneficiaries for `ok`, so a correction can change the beneficiary and not
    # only the amount — the material change the plan names first.
    beneficiaries = {"ok_one": uuid.uuid4(), "ok_two": uuid.uuid4(), "other": uuid.uuid4()}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for name, phone in TRADERS.items():
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
                (traders[name], f"Trader {name}", phone),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, 'Contact', %s, 'active', TRUE)",
                (traders[name], phone, encoded),
            )
        for key, owner, iban, full_name in (
            ("ok_one", "ok", IBAN_ONE, "Ali One"),
            ("ok_two", "ok", IBAN_TWO, "Reza Two"),
            ("other", "other", IBAN_ONE, "Someone Else"),
        ):
            connection.execute(
                "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
                "status, verification_status) VALUES (%s, %s, %s, %s, %s, 'active', "
                "'not_checked')",
                (beneficiaries[key], traders[owner], full_name, iban, iban),
            )

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
            "traders": traders,
            "beneficiaries": beneficiaries,
            "owner_url": migrated.owner_url,
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in(client: Any, trader: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login",
        json={"identifier": TRADERS[trader], "password": PASSWORD},
    )
    assert response.status_code == 200, response.text


def sign_in_admin(client: Any, username: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(client: Any) -> dict[str, str]:
    token = client.cookies.get(TRADER_CSRF_COOKIE) or client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def open_draft(world: dict[str, Any], beneficiary: str = "ok_one", value: str = "500") -> Any:
    client = world["client"]
    return client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiaries"][beneficiary]),
            "amount": {"value": value, "unit": "TOMAN"},
            "description": "original",
        },
        headers=csrf(client),
    ).json()


def correct(
    world: dict[str, Any],
    request_id: str,
    version: int,
    *,
    beneficiary: str = "ok_one",
    value: str = "600",
    description: str | None = "corrected",
    key: str | None = None,
    reason: str | None = "accountant asked",
) -> Any:
    client = world["client"]
    headers = {
        **csrf(client),
        "If-Match": f'"rv-{version}"',
        "Idempotency-Key": key or str(uuid.uuid4()),
    }
    return client.post(
        f"/api/v1/payment-requests/{request_id}/revisions",
        json={
            "beneficiary_id": str(world["beneficiaries"][beneficiary]),
            "amount": {"value": value, "unit": "TOMAN"},
            "description": description,
            "revision_reason": reason,
        },
        headers=headers,
    )


def submit(world: dict[str, Any], request_id: str, version: int) -> Any:
    """Hand the request to the centre, the way a trader does.

    Needed because a correction no longer submits as a side effect. Tests that wanted a
    `submitted_to_center` request used to get one by correcting a draft, which is exactly
    the behaviour that turned out to be wrong.
    """

    client = world["client"]
    return client.post(
        f"/api/v1/payment-requests/{request_id}/submit",
        json={},
        headers={
            **csrf(client),
            "If-Match": f'"rv-{version}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )


def revision_row(world: dict[str, Any], revision_id: str) -> dict[str, Any]:
    columns = ", ".join(REVISION_COLUMNS)
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            f"SELECT {columns} FROM payment_request_revisions WHERE id = %s", (revision_id,)
        ).fetchone()
    assert row is not None, f"revision {revision_id} is gone"
    return dict(zip(REVISION_COLUMNS, row, strict=True))


def test_a_correction_creates_revision_two_and_moves_the_pointer(
    world: dict[str, Any],
) -> None:
    """SVC-REV-001, the additive half."""

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)

    response = correct(world, created["request"]["id"], created["request"]["record_version"])
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["revision"]["revision_number"] == 2
    assert body["revision"]["id"] != created["revision"]["id"]
    assert body["request"]["current_revision_id"] == body["revision"]["id"]
    assert body["replayed"] is False
    # The state does not move. Document 06's transition table at `:640` gives a revision
    # the "same aggregate state", and this once asserted `submitted_to_center` because the
    # command set it unconditionally — which filed a draft the moment its owner edited it.
    # Resubmission is `submit`, from either origin (`:641`), and slice 7 proves that.
    assert body["request"]["status"] == "draft"


def test_the_previous_revision_is_byte_identical_afterwards(world: dict[str, Any]) -> None:
    """SVC-REV-001, and the property the whole milestone rests on.

    Every column, read before and after. Asserting only that the amount is unchanged
    would pass on a revision whose `content_hash` or `created_at` had been rewritten —
    and a row that can be edited in any field is not evidence of anything.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    first_id = created["revision"]["id"]

    before = revision_row(world, first_id)
    correct(world, created["request"]["id"], created["request"]["record_version"])
    after = revision_row(world, first_id)

    assert after == before, {
        column: (before[column], after[column])
        for column in REVISION_COLUMNS
        if before[column] != after[column]
    }


def test_superseded_at_is_left_null_rather_than_written(world: dict[str, Any]) -> None:
    """SVC-REV-001.

    Document 04 defines `superseded_at` and M5 does not write it. Setting it would be
    an update to an immutable row — and the migration grants no UPDATE, so it would
    fail at the privilege rather than succeed quietly. "Which revision is current" is
    already answered by `payment_requests.current_revision_id`; recording the same fact
    twice, where one copy needs a widened grant, trades the guarantee for a convenience.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    correct(world, created["request"]["id"], created["request"]["record_version"])

    assert revision_row(world, created["revision"]["id"])["superseded_at"] is None


def test_the_history_is_readable_in_order_and_complete(world: dict[str, Any]) -> None:
    """SVC-REV-002.

    Three corrections, then the question the milestone exists to answer: what did they
    submit the first time. Every revision must be present and the order must be the
    revision number's, not the timestamp's.

    **This used to reset the status between corrections with direct SQL, and the reset is
    now gone.** It existed because `create_revision` moved the request to
    `submitted_to_center` on every correction, which then refused the next one — so there
    was no route to revision 3 and a hand-written status stood in for the accountant's
    return. Slice 7 found that side effect had no mandate: document 06 `:640` leaves a
    revision in the "same aggregate state". A draft now stays a draft and takes as many
    corrections as its owner wants, which is what `:622` means by "freely in `draft`".

    The return path is a real transition and is driven as one, by the accountant who owns
    it, in `test_payment_request_review.py`'s journey test.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world, value="100")
    request_id = created["request"]["id"]

    version = created["request"]["record_version"]
    for value in ("200", "300", "400"):
        response = correct(world, request_id, version, value=value)
        assert response.status_code == 201, response.text
        version = response.json()["request"]["record_version"]

    history = client.get(f"/api/v1/payment-requests/{request_id}/revisions")
    assert history.status_code == 200, history.text
    body = history.json()

    assert [item["revision_number"] for item in body["items"]] == [1, 2, 3, 4]
    assert [item["entered_amount"]["value"] for item in body["items"]] == [
        "100",
        "200",
        "300",
        "400",
    ]
    assert body["current_revision_id"] == body["items"][-1]["id"]
    assert body["items"][0]["description"] == "original", (
        "the first submission is no longer readable, which is the one thing the history "
        "exists for"
    )


def test_a_correction_that_changes_nothing_is_refused(world: dict[str, Any]) -> None:
    """SVC-REV-003, reversed from what the plan first claimed.

    `04_Database_Schema.md:901` is `UNIQUE(payment_request_id, content_hash)`. A trader
    asked to correct something who resubmits it unchanged has not corrected it, and a
    second identical revision would reach a reviewer looking like new work.

    Refused with a message rather than an integrity error: the command compares against
    the current revision's hash and says what is wrong, and the constraint behind it is
    what makes the rule unbypassable.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world, value="500")

    identical = correct(
        world,
        created["request"]["id"],
        created["request"]["record_version"],
        value="500",
        description="original",
        reason=None,
    )

    assert identical.status_code == 400, identical.text
    assert identical.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        count = connection.execute(
            "SELECT count(*) FROM payment_request_revisions WHERE payment_request_id = %s",
            (created["request"]["id"],),
        ).fetchone()
    assert count is not None and count[0] == 1, "the refused correction was stored anyway"


def test_a_description_only_change_is_a_real_correction(world: dict[str, Any]) -> None:
    """SVC-REV-003, the other side of the line.

    The plan decides this explicitly: a description-only edit is still a new revision,
    because the description is submitted intent and a reviewer read it. So the hash must
    include it — and if it did not, this would be refused as a duplicate and a trader
    correcting their own explanatory note would be told they changed nothing.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world, value="500")

    response = correct(
        world,
        created["request"]["id"],
        created["request"]["record_version"],
        value="500",
        description="the same money, a clearer explanation",
    )

    assert response.status_code == 201, response.text
    assert response.json()["revision"]["revision_number"] == 2


def test_a_repeated_idempotency_key_replays_instead_of_creating(
    world: dict[str, Any],
) -> None:
    """SVC-REV-004.

    The retry-after-timeout case. Without a key the second attempt would try to create
    revision 3 identical to revision 2 — which the uniqueness constraint refuses, so the
    trader would be told their correction duplicates their own correction.

    `replayed` is surfaced in the body: a client that cannot tell a replay from a fresh
    write has to guess whether it succeeded the first time.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    key = str(uuid.uuid4())

    first = correct(
        world, created["request"]["id"], created["request"]["record_version"], key=key
    )
    assert first.status_code == 201
    assert first.json()["replayed"] is False

    # The same key, and the same body — including the stale `If-Match`, which is what a
    # real retry would send because it never saw the first response.
    second = correct(
        world, created["request"]["id"], created["request"]["record_version"], key=key
    )
    assert second.status_code == 201, second.text
    assert second.json()["replayed"] is True
    assert second.json()["revision"]["id"] == first.json()["revision"]["id"]

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        count = connection.execute(
            "SELECT count(*) FROM payment_request_revisions WHERE payment_request_id = %s",
            (created["request"]["id"],),
        ).fetchone()
    assert count is not None and count[0] == 2, "the replay created a third revision"


def test_a_reused_key_with_a_different_body_is_a_conflict(world: dict[str, Any]) -> None:
    """SVC-REV-004, the other direction.

    A replay is only correct for the *same* request. The same key with different content
    is a client bug, and answering with the first response would silently discard the
    second correction.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    key = str(uuid.uuid4())

    first = correct(
        world, created["request"]["id"], created["request"]["record_version"], key=key, value="600"
    )
    assert first.status_code == 201

    clashing = correct(
        world,
        created["request"]["id"],
        first.json()["request"]["record_version"],
        key=key,
        value="700",
    )
    assert clashing.status_code == 409, clashing.text


def test_creating_a_revision_requires_a_current_if_match(world: dict[str, Any]) -> None:
    """CON-REQ-002.

    Three answers again, and the row is read back after the stale one: "returns 412
    rather than overwriting" is two claims, and a route could answer 412 after having
    written.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    request_id = created["request"]["id"]
    path = f"/api/v1/payment-requests/{request_id}/revisions"
    body = {
        "beneficiary_id": str(world["beneficiaries"]["ok_one"]),
        "amount": {"value": "600", "unit": "TOMAN"},
    }

    without = client.post(
        path, json=body, headers={**csrf(client), "Idempotency-Key": str(uuid.uuid4())}
    )
    assert without.status_code == 428, without.text

    stale = client.post(
        path,
        json=body,
        headers={
            **csrf(client),
            "If-Match": '"rv-99"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert stale.status_code == 412, stale.text

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        count = connection.execute(
            "SELECT count(*) FROM payment_request_revisions WHERE payment_request_id = %s",
            (request_id,),
        ).fetchone()
    assert count is not None and count[0] == 1, "the stale correction was applied anyway"


def test_an_idempotency_key_is_required(world: dict[str, Any]) -> None:
    """SVC-REV-004.

    Required rather than optional. A correction without one is a correction that cannot
    be retried safely, and the client discovers that only after a timeout — when it is
    too late to add the header.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)

    response = client.post(
        f"/api/v1/payment-requests/{created['request']['id']}/revisions",
        json={
            "beneficiary_id": str(world["beneficiaries"]["ok_one"]),
            "amount": {"value": "600", "unit": "TOMAN"},
        },
        headers={
            **csrf(client),
            "If-Match": f'"rv-{created["request"]["record_version"]}"',
        },
    )
    assert response.status_code == 428, response.text


def test_a_correction_can_change_the_beneficiary(world: dict[str, Any]) -> None:
    """SVC-REV-001.

    The material change the plan names first, and the one that proves the snapshots are
    re-taken rather than copied: the new revision must carry the *new* beneficiary's
    name and IBAN, and the old revision must still carry the old ones.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world, beneficiary="ok_one")

    response = correct(
        world,
        created["request"]["id"],
        created["request"]["record_version"],
        beneficiary="ok_two",
    )
    assert response.status_code == 201, response.text

    assert response.json()["revision"]["beneficiary_iban_snapshot"] == IBAN_TWO
    assert response.json()["revision"]["beneficiary_name_snapshot"] == "Reza Two"
    assert revision_row(world, created["revision"]["id"])["beneficiary_iban_snapshot"] == IBAN_ONE


def test_a_trader_cannot_correct_another_traders_request(world: dict[str, Any]) -> None:
    """The ownership negative. `404`, so the id is not confirmed."""

    client = world["client"]

    sign_in(client, "other")
    theirs = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiaries"]["other"]),
            "amount": {"value": "500", "unit": "TOMAN"},
        },
        headers=csrf(client),
    ).json()

    sign_in(client, "ok")
    refused = correct(world, theirs["request"]["id"], theirs["request"]["record_version"])
    assert refused.status_code == 404, refused.text

    assert revision_row(world, theirs["revision"]["id"])["revision_number"] == 1


def test_a_trader_cannot_read_another_traders_revision_history(
    world: dict[str, Any],
) -> None:
    """The ownership negative on the history.

    This is the mandatory case "Admin response accidentally includes unrelated trader
    data" in its trader form: a history endpoint that ignored scope would hand over
    another trader's beneficiary names, IBAN snapshots and amounts in one response.
    """

    client = world["client"]

    sign_in(client, "other")
    theirs = client.post(
        "/api/v1/payment-requests",
        json={
            "beneficiary_id": str(world["beneficiaries"]["other"]),
            "amount": {"value": "500", "unit": "TOMAN"},
        },
        headers=csrf(client),
    ).json()

    sign_in(client, "ok")
    refused = client.get(f"/api/v1/payment-requests/{theirs['request']['id']}/revisions")
    assert refused.status_code == 404, refused.text
    assert "Someone Else" not in refused.text
    assert IBAN_ONE not in refused.text


def test_an_admin_without_the_revision_permission_is_refused(world: dict[str, Any]) -> None:
    """The permission negative for both routes.

    The GET carries no CSRF token and needs none, so its 403 can only be the permission.
    The permitted admin half is what makes the refusal about the grant.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    request_id = created["request"]["id"]

    sign_in_admin(client, "staff_bare")
    assert client.get(f"/api/v1/payment-requests/{request_id}/revisions").status_code == 403

    refused = client.post(
        f"/api/v1/payment-requests/{request_id}/revisions",
        json={
            "beneficiary_id": str(world["beneficiaries"]["ok_one"]),
            "amount": {"value": "600", "unit": "TOMAN"},
        },
        headers={
            **csrf(client),
            "If-Match": f'"rv-{created["request"]["record_version"]}"',
            "Idempotency-Key": str(uuid.uuid4()),
        },
    )
    assert refused.status_code == 403, refused.text

    sign_in_admin(client, "staff_granted")
    allowed = client.get(f"/api/v1/payment-requests/{request_id}/revisions")
    assert allowed.status_code == 200, allowed.text


def test_a_submitted_request_does_not_take_a_correction(world: dict[str, Any]) -> None:
    """The transition guard.

    Correcting a request while an accountant is reading it would move the content under
    them. Document 06 routes that through the review workflow — the accountant returns
    it, which is slice 7 — so this refuses rather than assuming.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    handed_over = submit(world, created["request"]["id"], created["request"]["record_version"])
    assert handed_over.status_code == 200, handed_over.text
    assert handed_over.json()["status"] == "submitted_to_center"

    # It is with the centre now, so its content may not move under the reader.
    refused = correct(
        world,
        created["request"]["id"],
        handed_over.json()["record_version"],
        value="700",
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["code"] == "BUSINESS_RULE_VIOLATION"


def test_the_correction_writes_its_catalogued_audit_action(world: dict[str, Any]) -> None:
    """`payment_request.revision_created` is in `audit_outbox_catalog.yaml`.

    The previous and new pointer are both recorded, so the trail says which revision
    replaced which rather than only that something changed.
    """

    client = world["client"]
    sign_in(client, "ok")
    created = open_draft(world)
    response = correct(world, created["request"]["id"], created["request"]["record_version"])

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT action, previous_values, new_values FROM audit_logs "
            "WHERE action = 'payment_request.revision_created' AND entity_id = %s",
            (created["request"]["id"],),
        ).fetchone()

    assert row is not None, "the correction wrote no audit row"
    assert row[1]["current_revision_id"] == created["revision"]["id"]
    assert row[2]["current_revision_id"] == response.json()["revision"]["id"]
    assert row[2]["revision_number"] == 2
