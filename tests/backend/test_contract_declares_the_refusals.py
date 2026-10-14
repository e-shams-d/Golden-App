"""A route that can refuse with 401 or 403 says so in the contract. F-13.

The acceptance pass measured `POST /bank-profiles` answering 401 and 403 while its OpenAPI entry
listed 201, 400 and 422 — and `POST /beneficiaries`, beside it, declaring both. The API client is
generated from that document, so an undeclared refusal is a status the generated types say cannot
happen.

What a route can refuse with is read from its dependencies, the way the server decides it:

- `authenticated_actor` anywhere in its dependency tree — directly or through `requires(...)` —
  means 401: no valid session.
- The same dependency refuses an unsafe method with 403 when the CSRF token or the origin is wrong
  (`_require_csrf`), and `requires(...)` refuses with 403 when the permission is missing. So an
  authenticated route declares 403 when its method is unsafe or it carries a permission guard.

No route is named in the rule, so a route added tomorrow is judged by it too.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest

UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class Operation(NamedTuple):
    method: str
    path: str
    authenticated: bool
    guarded: bool
    declared: frozenset[str]


def _depends_on(dependant: Any, target: Any) -> bool:
    return any(
        child.call is target or _depends_on(child, target) for child in dependant.dependencies
    )


def operations(app: Any) -> list[Operation]:
    from app.api.v1.auth import authenticated_actor
    from fastapi.routing import APIRoute
    from test_permission_guards import declared_permissions, routes_of

    schema = app.openapi()
    found = []
    for method, path, route in routes_of(app):
        # The reader also returns plain Starlette routes, which have no dependencies to read. The
        # guard test is what proves the API routes are still being read.
        if not isinstance(route, APIRoute):
            continue
        responses = schema["paths"][path][method.lower()].get("responses", {})
        found.append(
            Operation(
                method=method.upper(),
                path=path,
                authenticated=_depends_on(route.dependant, authenticated_actor),
                guarded=bool(declared_permissions(route)),
                declared=frozenset(str(code) for code in responses),
            )
        )
    return found


@pytest.fixture
def served(app_factory: Any) -> list[Operation]:
    app, _runtime, _settings = app_factory()
    return operations(app)


def test_the_reader_sees_the_routes_and_their_guards(served: list[Operation]) -> None:
    """Guard the guard: a reader that saw no authentication would find nothing to require."""

    by_shape = {(operation.method, operation.path): operation for operation in served}
    assert len(served) >= 150, f"only {len(served)} operations were read"
    assert sum(operation.authenticated for operation in served) >= 120

    profiles = by_shape[("POST", "/api/v1/bank-profiles")]
    assert (profiles.authenticated, profiles.guarded) == (True, True), profiles
    registration = by_shape[("POST", "/api/v1/traders/register")]
    assert registration.authenticated is False, registration


def test_every_refusal_a_route_can_make_is_in_the_contract(served: list[Operation]) -> None:
    undeclared = []
    for operation in served:
        if not operation.authenticated:
            continue
        missing = []
        if "401" not in operation.declared:
            missing.append("401")
        if (operation.method in UNSAFE or operation.guarded) and "403" not in operation.declared:
            missing.append("403")
        if missing:
            undeclared.append(f"{operation.method} {operation.path}: {', '.join(missing)}")

    assert undeclared == [], (
        "these routes can refuse with a status their contract entry does not list — add "
        "UNAUTHENTICATED_RESPONSE and REFUSED_RESPONSE from app/api/contract.py:\n"
        + "\n".join(undeclared)
    )
