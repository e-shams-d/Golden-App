"""Reading the messages the system has been writing for two milestones. M11 slice 1.

`05_API_Specification.md` §22.3 at `:2077`, `15_Agent_Implementation_Plan.md:1298`.

**The table has existed since M9 slice 7 and nothing could read a row of it.** M9's own G-5 decided
that a failed payment reaches its trader *as a notification rather than as a publication*; M10
slice 8 added a second producer for gold that is ready to dispatch. Both wrote rows into a table
with no route. This file is the first evidence that any of it reaches a person.

**Rows are seeded directly, and that is deliberate.** `test_notification_projection.py` already
proves that events become messages, that a redelivery produces one message, and that a failed
projection changes no money. Re-walking that chain here would test the projection a second time and
the read contract barely at all — and it would make the two-recipient cases, which are the point,
almost impossible to construct. What this file tests is who may see a row and what a page of them
looks like.

**Two recipients in every scope test, never one.** `SVC-NOTIFY-001` exists because the
single-recipient version of `mark-all-read` passes against an implementation that marks the entire
table: with one person's rows in the database, "marked everything" and "marked mine" are the same
observation. The second recipient is what makes them different, and the assertion is on *their*
rows being untouched rather than on the caller's count.

Covers: SEC-NOTIFY-001, SVC-NOTIFY-001, API-NOTIFY-001.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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

FIRST_PHONE = "+989120031001"
SECOND_PHONE = "+989120031002"
ADMIN_USERNAME = "notify_accountant"

# `notification_type` and `entity_type` both carry CHECKs naming the values M9 and M10 enumerated.
# Using a real one rather than a placeholder means a value removed from either tuple fails here
# instead of passing against a test that invented its own vocabulary.
TYPE = "payment_result_published"
ENTITY = "payment_request"


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
        local_storage_root=tmp_path_factory.mktemp("notify-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="y" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids: dict[str, uuid.UUID] = {}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for key, phone, name in (
            ("first", FIRST_PHONE, "First Business"),
            ("second", SECOND_PHONE, "Second Business"),
        ):
            trader_id = uuid.uuid4()
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
                (trader_id, name, phone),
            )
            row = connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, %s, %s, 'active', TRUE) RETURNING id",
                (trader_id, phone, name, encoded),
            ).fetchone()
            assert row is not None
            ids[key] = row[0]

        connection.execute(
            "INSERT INTO admin_users (username, full_name, password_hash, status) "
            "VALUES (%s, 'Notified Accountant', %s, 'active')",
            (ADMIN_USERNAME, encoded),
        )
        connection.execute(
            "INSERT INTO admin_user_roles (admin_user_id, role_id) "
            "SELECT u.id, r.id FROM admin_users u, roles r "
            "WHERE u.username = %s AND r.code = 'accountant'",
            (ADMIN_USERNAME,),
        )
        admin = connection.execute(
            "SELECT id FROM admin_users WHERE username = %s", (ADMIN_USERNAME,)
        ).fetchone()
        assert admin is not None
        ids["admin"] = admin[0]
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


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(autouse=True)
def an_empty_table(world: dict[str, Any]) -> Iterator[None]:
    """The database is module-scoped, so a test that counted rows was counting earlier tests too."""

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute("DELETE FROM notifications")
        connection.commit()
    yield


def rows(world: dict[str, Any], sql: str, *parameters: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        return connection.execute(sql, parameters).fetchall()


def notify(
    world: dict[str, Any],
    recipient: uuid.UUID,
    *,
    actor_type: str = "trader_user",
    title: str = "A result was published",
    created_at: datetime | None = None,
    status: str = "unread",
) -> uuid.UUID:
    """One seeded message. Returns its id.

    `created_at` is settable because `API-NOTIFY-001` needs rows that share a timestamp, which is
    the only condition under which an unstable sort is observable.
    """

    notification_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO notifications (id, recipient_actor_type, recipient_actor_id, "
            "notification_type, title, body, entity_type, entity_id, status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, 'The centre published a result.', %s, %s, %s, "
            "COALESCE(%s, now()))",
            (
                notification_id,
                actor_type,
                recipient,
                TYPE,
                title,
                ENTITY,
                uuid.uuid4(),
                status,
                created_at,
            ),
        )
        connection.commit()
    return notification_id


def sign_in_trader(world: dict[str, Any], phone: str) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": phone, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def sign_in_admin(world: dict[str, Any]) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": ADMIN_USERNAME, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def csrf(world: dict[str, Any]) -> dict[str, str]:
    client = world["client"]
    token = client.cookies.get(ADMIN_CSRF_COOKIE) or client.cookies.get(TRADER_CSRF_COOKIE)
    assert token, "signed in but no CSRF cookie was set"
    return {CSRF_HEADER: token}


def test_a_recipient_sees_only_notifications_addressed_to_them(world: dict[str, Any]) -> None:
    """SEC-NOTIFY-001. The scope is the row's own recipient, and it is not optional.

    Two businesses, three messages, and the assertion is on **both directions**: the first trader
    sees their two and the second sees their one. A test that only checked the first would pass
    against a route that returned everything to everybody as long as the first trader happened to
    own the earliest rows.
    """

    mine_a = notify(world, world["first_id"], title="Mine, the first")
    mine_b = notify(world, world["first_id"], title="Mine, the second")
    theirs = notify(world, world["second_id"], title="Not mine at all")

    sign_in_trader(world, FIRST_PHONE)
    first = world["client"].get("/api/v1/notifications")
    assert first.status_code == 200, first.text
    seen = {item["id"] for item in first.json()["items"]}
    assert seen == {str(mine_a), str(mine_b)}
    assert str(theirs) not in seen
    assert first.json()["unread_count"] == 2

    sign_in_trader(world, SECOND_PHONE)
    second = world["client"].get("/api/v1/notifications")
    assert second.status_code == 200, second.text
    assert {item["id"] for item in second.json()["items"]} == {str(theirs)}
    assert second.json()["unread_count"] == 1


def test_a_notification_body_carries_no_recipient_to_compare_against(
    world: dict[str, Any],
) -> None:
    """`extra="forbid"` is not what proves this — the absence of the field is.

    A recipient id in the response would be a value a client could hold up against somebody else's,
    and it would tell a trader the internal identifier of a person the system knows about. Every
    row in a response is the caller's own by construction, so the field has nothing to say.
    """

    notify(world, world["first_id"])
    sign_in_trader(world, FIRST_PHONE)

    item = world["client"].get("/api/v1/notifications").json()["items"][0]
    assert "recipient_actor_id" not in item
    assert "recipient_actor_type" not in item
    assert "deduplication_key" not in item


def test_marking_somebody_elses_notification_read_is_not_found(world: dict[str, Any]) -> None:
    """404 rather than 403, and the row is unchanged.

    Two assertions, because the status code alone is the weaker half: a route that refused with 404
    *after* writing would satisfy a test that only read the response. The database is checked.
    """

    theirs = notify(world, world["second_id"])

    sign_in_trader(world, FIRST_PHONE)
    response = world["client"].post(
        f"/api/v1/notifications/{theirs}/mark-read", headers=csrf(world)
    )
    assert response.status_code == 404, response.text

    state = rows(world, "SELECT status, read_at FROM notifications WHERE id = %s", theirs)
    assert state == [("unread", None)]


def test_a_notification_that_does_not_exist_is_the_same_refusal(world: dict[str, Any]) -> None:
    """The two cases must be indistinguishable, or the 404 above is a disclosure.

    If "somebody else's" and "no such row" answered differently, a caller could enumerate which
    identifiers name real notifications — which is the whole reason `app/security/ownership.py`
    prefers 404 to 403.
    """

    theirs = notify(world, world["second_id"])
    sign_in_trader(world, FIRST_PHONE)

    absent = world["client"].post(
        f"/api/v1/notifications/{uuid.uuid4()}/mark-read", headers=csrf(world)
    )
    present = world["client"].post(
        f"/api/v1/notifications/{theirs}/mark-read", headers=csrf(world)
    )
    assert absent.status_code == present.status_code == 404
    assert absent.json()["error"]["code"] == present.json()["error"]["code"]


def test_marking_one_read_records_when_and_does_not_move_it_again(world: dict[str, Any]) -> None:
    """Idempotent without an idempotency key, and the second call is what proves it.

    `read_at` is the moment somebody first read the message. A second call is a client retrying,
    not a person reading twice, so it returns the row unchanged rather than overwriting the time.
    """

    mine = notify(world, world["first_id"])
    sign_in_trader(world, FIRST_PHONE)

    first = world["client"].post(f"/api/v1/notifications/{mine}/mark-read", headers=csrf(world))
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "read"
    first_read_at = first.json()["read_at"]
    assert first_read_at is not None

    second = world["client"].post(f"/api/v1/notifications/{mine}/mark-read", headers=csrf(world))
    assert second.status_code == 200, second.text
    assert second.json()["read_at"] == first_read_at


def test_marking_all_read_leaves_every_other_recipient_untouched(world: dict[str, Any]) -> None:
    """SVC-NOTIFY-001, and the reason the second recipient exists.

    With one person's rows in the table, "marked everything" and "marked only mine" are the same
    observation — the single-recipient version of this test passes against
    `UPDATE notifications SET status = 'read'` with no WHERE clause at all. The assertion that
    carries the weight is on the *other* trader's rows.
    """

    mine_a = notify(world, world["first_id"])
    mine_b = notify(world, world["first_id"])
    theirs_a = notify(world, world["second_id"])
    theirs_b = notify(world, world["second_id"])

    sign_in_trader(world, FIRST_PHONE)
    response = world["client"].post("/api/v1/notifications/mark-all-read", headers=csrf(world))
    assert response.status_code == 200, response.text
    assert response.json() == {"marked": 2, "unread_count": 0}

    mine = rows(
        world,
        "SELECT status FROM notifications WHERE id = ANY(%s) ORDER BY id",
        [mine_a, mine_b],
    )
    assert mine == [("read",)] * 2

    theirs = rows(
        world,
        "SELECT status, read_at FROM notifications WHERE id = ANY(%s)",
        [theirs_a, theirs_b],
    )
    assert theirs == [("unread", None)] * 2


def test_marking_all_read_when_nothing_is_unread_says_so(world: dict[str, Any]) -> None:
    """`marked: 0` is the only way a client can tell "nothing to do" from "reached nothing"."""

    notify(world, world["first_id"], status="read")
    sign_in_trader(world, FIRST_PHONE)

    response = world["client"].post("/api/v1/notifications/mark-all-read", headers=csrf(world))
    assert response.status_code == 200, response.text
    assert response.json()["marked"] == 0


def test_an_admin_reads_their_own_and_a_trader_cannot_read_it(world: dict[str, Any]) -> None:
    """One path, two audiences, and the same mechanism — which is why the route is not `DUAL`.

    `recipient_actor_type` is part of the scope, not decoration. Without it a trader user id and an
    admin user id are both just UUIDs, and a collision — or a forged one — would cross the audience
    boundary `12_Security_RBAC_Audit.md:305` requires to be kept apart everywhere.
    """

    for_staff = notify(
        world, world["admin_id"], actor_type="admin_user", title="A queue needs attention"
    )

    sign_in_admin(world)
    staff = world["client"].get("/api/v1/notifications")
    assert staff.status_code == 200, staff.text
    assert {item["id"] for item in staff.json()["items"]} == {str(for_staff)}

    sign_in_trader(world, FIRST_PHONE)
    trader = world["client"].get("/api/v1/notifications")
    assert trader.status_code == 200, trader.text
    assert trader.json()["items"] == []

    refused = world["client"].post(
        f"/api/v1/notifications/{for_staff}/mark-read", headers=csrf(world)
    )
    assert refused.status_code == 404, refused.text


def test_the_same_actor_id_in_the_other_audience_is_a_different_recipient(
    world: dict[str, Any],
) -> None:
    """The audience half of the scope, isolated.

    The test above varies both the recipient id *and* the audience at once, so it passes against an
    implementation that filters on the id alone. This one holds the id fixed: a notification
    addressed to `admin_user` with the *trader's* id must not reach that trader.
    """

    crossed = notify(world, world["first_id"], actor_type="admin_user")
    mine = notify(world, world["first_id"])

    sign_in_trader(world, FIRST_PHONE)
    response = world["client"].get("/api/v1/notifications")
    assert response.status_code == 200, response.text
    assert {item["id"] for item in response.json()["items"]} == {str(mine)}
    assert str(crossed) not in response.text


def test_the_list_is_cursor_paginated_and_stably_ordered(world: dict[str, Any]) -> None:
    """API-NOTIFY-001. Six rows sharing one timestamp, walked two at a time.

    **The shared timestamp is the test.** §19 `:1298` asks for a stable order, and a sort on
    `created_at` alone looks correct against rows that differ by a second — every page boundary
    lands somewhere unambiguous. Two notifications written by one dispatcher pass share a
    transaction and can share a timestamp exactly, and that is when a non-unique sort starts
    repeating and dropping rows. `NOTIFICATION_LIST_SPEC` adds `id` as the unique tiebreak; this
    walks the boundary that would expose its absence.
    """

    stamp = datetime.now(UTC) - timedelta(hours=1)
    expected = {str(notify(world, world["first_id"], created_at=stamp)) for _ in range(6)}

    sign_in_trader(world, FIRST_PHONE)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(6):
        query = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        response = world["client"].get("/api/v1/notifications", params=query)
        assert response.status_code == 200, response.text
        body = response.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert cursor is None, "the walk did not terminate"
    assert len(seen) == len(set(seen)), f"a row was returned twice across pages: {seen}"
    assert set(seen) == expected


def test_a_sort_the_spec_does_not_allow_is_refused(world: dict[str, Any]) -> None:
    """Refused, not ignored.

    An ignored sort returns a different page than the caller asked for and says nothing about it,
    which is the failure `app/db/pagination.py` was written to prevent. `title` is chosen
    deliberately: it is a real column of the table, so the refusal is about the allowlist rather
    than about the name not existing.
    """

    notify(world, world["first_id"])
    sign_in_trader(world, FIRST_PHONE)

    response = world["client"].get("/api/v1/notifications", params={"sort": "title"})
    assert response.status_code == 400, response.text


def test_filtering_narrows_the_caller_s_own_rows_and_not_the_scope(world: dict[str, Any]) -> None:
    """A filter is applied *inside* the recipient scope, never instead of it.

    The second trader's row is unread too, so a `status=unread` filter that replaced the scope
    rather than narrowing it would return it.
    """

    unread = notify(world, world["first_id"])
    notify(world, world["first_id"], status="read")
    notify(world, world["second_id"])

    sign_in_trader(world, FIRST_PHONE)
    response = world["client"].get("/api/v1/notifications", params={"status": "unread"})
    assert response.status_code == 200, response.text
    assert {item["id"] for item in response.json()["items"]} == {str(unread)}


def test_an_unauthenticated_caller_reaches_none_of_the_three(world: dict[str, Any]) -> None:
    """No session, no recipient, and therefore nothing to scope by."""

    mine = notify(world, world["first_id"])
    world["client"].cookies.clear()

    assert world["client"].get("/api/v1/notifications").status_code == 401
    assert world["client"].post(f"/api/v1/notifications/{mine}/mark-read").status_code == 401
    assert world["client"].post("/api/v1/notifications/mark-all-read").status_code == 401
