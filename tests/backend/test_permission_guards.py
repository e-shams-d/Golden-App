"""The permission guards, and the two lists they depend on staying honest.

Two gates here, and they cover different failures.

The **drift gate** compares the inlined `APPROVED_PERMISSIONS` against the
approved catalogue. The copy exists because `docs/` is not in the container image
— a module parsing the catalogue at import would crash every deployment on
start-up, which is exactly what the first version of `app/security/permissions.py`
did. The copy is the right answer; an ungated copy is not.

The **declaration gate** requires every route under `/api/v1` either to declare a
permission or to appear in an explicit allowlist. `12_Security_RBAC_Audit.md:629`
requires unknown permissions to fail closed, and a route that simply forgot to
declare one is the same hole by a different route. Making the omission a build
failure is the only version that survives a busy week.

Covers: SEC-PERM-001, SEC-PERM-003, SEC-PERM-004, SEC-PERM-005, SEC-PERM-006,
SEC-PERM-007, SEC-PERM-008.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from app.security.permission_catalogue import APPROVED_PERMISSIONS
from app.security.permissions import UnknownPermission, declare

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.rbac_catalogue import (  # noqa: E402
    deprecated_aliases,
    permissions,
)

# Routes that legitimately carry no permission, each with the reason. An entry
# here is a decision; the absence of an entry is a build failure.
#
# Keyed by (method, path) rather than by prefix: a prefix rule would silently
# exempt every future route someone mounted underneath it, which is the failure
# this gate exists to prevent.
UNGUARDED_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/health/live"): "liveness must answer before anything is ready",
    ("GET", "/api/v1/health/ready"): "readiness is consumed by the orchestrator, not a user",
    ("GET", "/api/v1/health/dependencies"): "operations token, not a session permission",
    ("GET", "/api/v1/health/workers"): "operations token, not a session permission",
    ("GET", "/api/v1/operations/background-processing"): "operations token",
    ("GET", "/api/v1/operations/release-evidence"): "operations token",
    ("GET", "/api/v1/meta/release"): "static contract metadata, no actor involved",
    # FastAPI's own, and already absent in production:
    # `test_production_does_not_publish_openapi_or_interactive_docs` asserts they
    # 404 there. Listed rather than filtered out by pattern, because a filter
    # would also hide a real route somebody named `/docs`.
    ("GET", "/api/v1/openapi.json"): "generated contract; 404 in production",
    ("GET", "/api/v1/docs"): "interactive docs; 404 in production",
    ("POST", "/api/v1/auth/admin/login"): "authentication is what establishes an actor",
    ("POST", "/api/v1/auth/trader/login"): "authentication is what establishes an actor",
    ("GET", "/api/v1/auth/me"): "reads only the caller's own session",
    ("POST", "/api/v1/auth/logout"): "revokes only the caller's own session",
    ("GET", "/api/v1/auth/sessions"): "auth.session.read_own is implied by ownership",
    ("POST", "/api/v1/auth/sessions/{session_id}/revoke"): "own session; scoped by ownership",
    # Ownership-scoped, not permission-scoped. A trader resolves no permissions
    # at all (doc 04:405), so `requires(...)` has nothing to check; the guard is
    # ActorContext.trader_id, and tests/integration/test_trader_isolation.py is
    # what proves it bites.
    # Re-proving presence is not an entitlement, so there is no permission to
    # declare. What it needs is a session, which the actor dependency supplies;
    # the purpose and resource bindings are what stop it authorising anything
    # other than the one action it was obtained for.
    ("POST", "/api/v1/auth/reauthenticate"): "raises assurance; grants nothing",
    ("GET", "/api/v1/me/trader/profile"): "ownership-scoped to the caller's own trader",
    ("PATCH", "/api/v1/me/trader/profile"): "ownership-scoped; allowlist excludes identity",
    ("POST", "/api/v1/center-profile/rename"): (
        "M2's exemplar command, written before guards existed; slice 8 gives it settings.manage"
    ),
}


def declared_permissions(route: object) -> set[str]:
    """Permissions a route declares, read from its dependency graph."""

    found: set[str] = set()
    dependant = getattr(route, "dependant", None)
    for dependency in getattr(dependant, "dependencies", []) or []:
        call = getattr(dependency, "call", None)
        for value in getattr(call, "__closure__", None) or ():
            contents = value.cell_contents
            if isinstance(contents, str) and contents in APPROVED_PERMISSIONS:
                found.add(contents)
    return found


def routes_of(app: object) -> list[tuple[str, str, object]]:
    """Every concrete `/api/v1` route, with its dependency graph.

    Three things about this FastAPI version make a flat read wrong, and each one
    on its own would have made the gate vacuous:

    1. `include_router` stores a private `_IncludedRouter` wrapper, not the
       routes. `app.routes` and `api_v1_router.routes` both show wrappers plus the
       two docs routes.
    2. The real `APIRoute` objects hang off `wrapper.original_router.routes`.
    3. Their `path` is **unprefixed** — `/health/live`, not `/api/v1/health/live`.
       The prefix lives on `wrapper.include_context.prefix` and has to be
       accumulated during the descent.

    Missing (3) is what made the first working version return two routes: every
    endpoint was found and then filtered out for not starting with `/api/v1`.

    None of this is public API, which is exactly why
    `test_the_route_reader_finds_the_real_endpoints` pins a floor and a known
    path. A FastAPI upgrade that changes the structure fails the gate loudly
    rather than quietly checking nothing.
    """

    found: list[tuple[str, str, object]] = []
    seen: set[int] = set()

    def walk(node: object, prefix: str) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))

        context = getattr(node, "include_context", None)
        nested_prefix = prefix + (getattr(context, "prefix", "") or "")

        nested = getattr(node, "original_router", None)
        if nested is not None:
            walk(nested, nested_prefix)

        for child in getattr(node, "routes", []) or []:
            walk(child, nested_prefix)

        path = getattr(node, "path", None)
        methods = getattr(node, "methods", None) or set()
        if not path:
            return
        full = path if path.startswith("/api/v1") else f"{prefix}{path}"
        if not full.startswith("/api/v1"):
            return
        for method in sorted(methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            found.append((method, full, node))

    walk(app, "")
    return found


@pytest.fixture
def api_routes_list(app_factory: Any) -> list[tuple[str, str, object]]:
    app, _runtime, _settings = app_factory()
    return routes_of(app)


class TestInlinedCatalogue:
    def test_the_inlined_copy_matches_the_approved_catalogue(self) -> None:
        """The copy exists because docs/ is not in the image; this keeps it honest."""

        catalogue = {entry.code for entry in permissions()}

        assert catalogue == APPROVED_PERMISSIONS, (
            "the inlined permission list has drifted from "
            "docs/governance/permission_catalog.yaml. Missing: "
            f"{sorted(catalogue - APPROVED_PERMISSIONS)}; extra: "
            f"{sorted(APPROVED_PERMISSIONS - catalogue)}"
        )

    def test_the_copy_is_not_empty(self) -> None:
        """Guard the guard: two empty sets are equal."""

        assert len(APPROVED_PERMISSIONS) > 100

    def test_no_deprecated_alias_is_declarable(self) -> None:
        """SEC-PERM-001's other half.

        Doc 05's spellings map to canonical targets but must not themselves be
        declarable: `payment_batch.approve` names a mutable container where
        `payment_batch_version.approve` names the exact version reviewed, and an
        approval bound to the container can outlive the content it approved.
        """

        for alias in deprecated_aliases():
            assert alias not in APPROVED_PERMISSIONS, (
                f"{alias} is a deprecated document-05 spelling and must not be declarable"
            )
            with pytest.raises(UnknownPermission):
                declare(alias)


class TestDeclare:
    def test_a_typo_fails_immediately(self) -> None:
        """SEC-PERM-003.

        At declare time rather than at request time: a route declaring
        `payment_batch.aprove` would otherwise deny every caller silently, and the
        symptom — "the manager cannot approve" — points at the grant rather than
        at the typo.
        """

        with pytest.raises(UnknownPermission, match="aprove"):
            declare("payment_batch_version.aprove")

    def test_a_known_permission_passes_through(self) -> None:
        assert declare("role.manage") == "role.manage"


class TestRouteDeclarations:
    def test_every_route_declares_a_permission_or_is_listed(
        self, api_routes_list: list[tuple[str, str, object]]
    ) -> None:
        """SEC-PERM-004. The omission is a build failure, not a review finding."""

        undeclared = [
            f"{method} {path}"
            for method, path, route in api_routes_list
            if not declared_permissions(route) and (method, path) not in UNGUARDED_ROUTES
        ]

        assert undeclared == [], (
            "these routes declare no permission and are not on the explicit "
            f"allowlist: {undeclared}. Either declare one with `requires(...)` or "
            "add an entry to UNGUARDED_ROUTES saying why it needs none."
        )

    def test_the_allowlist_names_only_routes_that_exist(
        self, api_routes_list: list[tuple[str, str, object]]
    ) -> None:
        """Guard the guard: a stale entry silently exempts nothing, forever.

        And worse, it would go on looking like a considered decision — a renamed
        route would drop out of the gate entirely while its old name sat here
        reading as though it had been thought about.
        """

        live = {(method, path) for method, path, _ in api_routes_list}
        stale = sorted(
            f"{method} {path}" for method, path in UNGUARDED_ROUTES if (method, path) not in live
        )

        assert stale == [], f"allowlist entries for routes that no longer exist: {stale}"

    def test_the_route_reader_finds_the_real_endpoints(
        self, api_routes_list: list[tuple[str, str, object]]
    ) -> None:
        """Guard the guard: a flat pass over the router sees only wrappers.

        FastAPI nests each included router, so the first version of this reader
        returned nothing and every assertion above passed vacuously. Pinning a
        floor and a known path means that failure mode is loud.
        """

        routes = api_routes_list
        paths = {path for _, path, _ in routes}

        assert len(routes) >= 14, f"only {len(routes)} routes found; the reader is not recursing"
        assert "/api/v1/auth/admin/login" in paths

    def test_the_gate_can_see_a_declaration(self) -> None:
        """Guard the guard, the other way.

        If `declared_permissions` always returned an empty set, the gate above
        would still pass for every allowlisted route and quietly stop checking
        the rest. This requires the reader to find at least one real declaration,
        so the mechanism is proved rather than assumed.
        """

        from app.api.v1.auth import requires
        from fastapi import APIRouter

        probe = APIRouter()

        @probe.get("/probe", dependencies=[requires("role.read")])
        def _handler() -> None: ...

        found = {permission for route in probe.routes for permission in declared_permissions(route)}

        assert found == {"role.read"}, (
            "the declaration reader found nothing on a route that declares "
            "role.read, so the gate above is vacuous"
        )
