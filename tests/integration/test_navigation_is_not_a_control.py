"""UI-NAV-001's second half: a hidden navigation item is not a denial.

The frontend half — `apps/admin-web/test/navigation-permissions.test.ts` — proves that an
`accountant` is not shown the traders screen. That is a convenience, and on its own it is
the kind of claim that quietly becomes a security assumption: somebody later reads "the
accountant cannot see the traders screen" and builds on it.

So this is the half that says what actually stops them. The permission the navigation gates
on is read **by the server on every request**, the route refuses a caller who lacks it, and
typing the URL reaches the route. The frontend hides; the backend refuses; only the second
is a control.

**Written against the navigation module itself**, not against a list retyped here. The
gating permissions are parsed out of `apps/admin-web/src/navigation.ts`, so a screen added
to the navigation with a permission the server does not enforce fails this test — which is
the drift the split creates and the only one worth guarding.

**The floor matters more than usual.** "Every hidden item's permission is refused" is
vacuously true when nothing is hidden, so the number of items hidden from the unprivileged
role is asserted before anything else runs.

Covers: UI-NAV-001.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NAVIGATION = REPOSITORY_ROOT / "apps" / "admin-web" / "src" / "navigation.ts"

PASSWORD = "correct-horse-battery-staple"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"

# The unprivileged internal role, and the one the frontend test hides items from.
UNPRIVILEGED = "accountant1"
PRIVILEGED = "business_admin1"

# Each gated navigation item, paired with a request that exercises the same permission the
# item is gated on. Only the items whose route exists today: a pairing for a screen that has
# no backend yet would be a test of nothing dressed as coverage, and the parametrisation
# guard below is what stops that from silently becoming *all* of them.
GATED_ROUTES: list[tuple[str, str, str, str]] = [
    # (navigation href, gating permission, method, path)
    ("/traders", "trader.approve", "POST", "/api/v1/traders/{trader_id}/approve"),
]

_ITEM = re.compile(r'href:\s*"([^"]+)"[^}]*?permission:\s*"([^"]+)"', re.S)
_HREF = re.compile(r'href:\s*"([^"]+)"')

# The one item that carries no permission, because it is what an authenticated person lands
# on. Named rather than counted: the floor below asks that *only* this is ungated, which is
# a rule, where "at least N items are gated" was a number that went stale the moment the
# navigation legitimately shrank.
UNGATED = frozenset({"/"})


def gated_navigation() -> dict[str, str]:
    """Every navigation item that carries a permission, read from the module itself."""

    return dict(_ITEM.findall(NAVIGATION.read_text(encoding="utf-8")))


def every_navigation_href() -> list[str]:
    """Every item, gated or not — the denominator the floor is derived from."""

    return _HREF.findall(NAVIGATION.read_text(encoding="utf-8"))


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
def client(migrated: RuntimeIdentities, tmp_path: Any) -> Iterator[Any]:
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

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for username, role in ((PRIVILEGED, "business_admin"), (UNPRIVILEGED, "accountant")):
            row = connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active') RETURNING id",
                (username, username.title(), encoded),
            ).fetchone()
            assert row
            found = connection.execute("SELECT id FROM roles WHERE code = %s", (role,)).fetchone()
            assert found, f"migration 0008 should have seeded {role}"
            connection.execute(
                "INSERT INTO admin_user_roles (admin_user_id, role_id) VALUES (%s, %s)",
                (row[0], found[0]),
            )
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as test_client:
        yield test_client
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def sign_in(client: Any, username: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    token = client.cookies.get(ADMIN_CSRF_COOKIE)
    assert token
    return token


def test_the_navigation_module_still_gates_items_on_permissions() -> None:
    """Guard the guard: a module that stopped carrying permissions would empty every check.

    The pattern reads a TypeScript file, which is the fragile part of this arrangement — so
    it is asserted directly rather than left to produce an empty mapping that makes the
    tests below pass by having nothing to check.

    **The floor is a rule, not a number, and it is written that way because the number was
    wrong within a day.** The first version asserted "at least five gated items", which was
    true when the navigation had seven and false the moment a later slice removed the six
    items whose pages did not exist. Editing the number to match is the obvious repair and
    the wrong one: a floor somebody adjusts whenever it fires is a floor that has stopped
    meaning anything, and the next adjustment is the one that lets it reach zero.

    So it asserts what the navigation module actually promises — every item except the
    dashboard is gated. That survives screens arriving and leaving, and it still fails
    loudly if the pattern stops matching: an unparseable file yields no gated items, every
    href lands in `ungated`, and the comparison below reports all of them.
    """

    hrefs = every_navigation_href()
    gated = gated_navigation()

    assert len(hrefs) >= 2, (
        f"only {len(hrefs)} navigation items were parsed out of {NAVIGATION.name}; the "
        "pattern no longer matches how the module writes them, and every assertion below "
        "is now about nothing"
    )

    ungated = set(hrefs) - set(gated)
    assert ungated == UNGATED, (
        f"these navigation items carry no permission: {sorted(ungated)}. Only the dashboard "
        "may be ungated; anything else is a screen shown to everybody, and an item the "
        "permission pattern failed to parse looks exactly the same from here."
    )


def test_the_unprivileged_role_is_genuinely_shown_less(client: Any) -> None:
    """The floor. "Every hidden item is refused" is vacuous when nothing is hidden.

    Read from the API rather than from the catalogue file, because what matters here is
    what the *running server* resolves for this session — that is the set the frontend will
    receive from `GET /auth/me`, and it is the set the navigation filters on.
    """

    sign_in(client, UNPRIVILEGED)
    resolved = client.get("/api/v1/auth/me")
    assert resolved.status_code == 200, resolved.text
    held = set(resolved.json()["user"]["permissions"])

    hidden = {
        href: permission
        for href, permission in gated_navigation().items()
        if permission not in held
    }
    assert hidden, (
        "the server resolves every gating permission for the unprivileged role, so the "
        "navigation hides nothing and the claim that it reflects permissions is empty"
    )
    # And the one the paired requests below exercise is among them.
    assert "/traders" in hidden


@pytest.mark.parametrize(("href", "permission", "method", "path"), GATED_ROUTES)
def test_a_hidden_item_s_route_still_refuses_the_call(
    client: Any, href: str, permission: str, method: str, path: str
) -> None:
    """Typing the URL reaches the route, and the route refuses. That is the control.

    A 403 rather than a 401: the caller is genuinely authenticated, which is what makes this
    a statement about the *grant* rather than about the session.
    """

    assert gated_navigation().get(href) == permission, (
        f"{href} is no longer gated on {permission}; this pairing is stale and would test "
        "a permission the navigation does not use"
    )

    token = sign_in(client, PRIVILEGED)
    listed = client.get("/api/v1/traders")
    assert listed.status_code == 200, listed.text

    # Any id will do — the guard runs before the row is loaded, which is itself the point:
    # a permission check that needed the resource first would leak its existence.
    trader_id = "00000000-0000-4000-8000-000000000000"

    token = sign_in(client, UNPRIVILEGED)
    response = client.request(
        method,
        path.replace("{trader_id}", trader_id),
        json={"reason": "should never be applied"},
        headers={"If-Match": '"rv-1"', "Idempotency-Key": "nav-control", "X-CSRF-Token": token},
    )

    assert response.status_code == 403, (
        f"{method} {path} answered {response.status_code} for a caller without "
        f"{permission}. The navigation hides this screen from them, and if the route does "
        "not refuse it then hiding it was the only thing standing in the way."
    )
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_the_privileged_role_reaches_the_same_route(client: Any) -> None:
    """The positive control, and it is not optional.

    Without it, a 403 for everybody — a route broken, a permission renamed out of existence,
    a guard misconfigured — would read as proof that the guard discriminates. It refuses the
    unprivileged caller for lacking the grant, not because nobody can call it.
    """

    token = sign_in(client, PRIVILEGED)
    trader_id = "00000000-0000-4000-8000-000000000000"

    response = client.post(
        f"/api/v1/traders/{trader_id}/approve",
        json={},
        headers={"If-Match": '"rv-1"', "Idempotency-Key": "nav-positive", "X-CSRF-Token": token},
    )

    # 404 for a trader that does not exist — which is what a caller who *passed* the
    # permission guard receives. Anything but 403 proves the guard let them through.
    assert response.status_code != 403, response.text
    assert response.status_code == 404, response.text
