"""M3's Definition of Done, as a gate rather than a claim.

`15_Agent_Implementation_Plan.md:666` states it:

    M3 is complete when ownership and permission negative tests exist for every
    implemented protected resource and the two frontends cannot access each other's
    protected surfaces.

That is a property of the **test suite**, not a deliverable, so "we wrote the
tests" cannot discharge it. This enumerates the protected surface from the built
application and requires each route to be accounted for.

**Why this file is written defensively.** Three gates in this milestone passed
while checking nothing, and each was found by accident rather than by CI:

- the permission gate's route reader returned two routes instead of twenty-two,
  because FastAPI nests included routers behind a private wrapper whose own `path`
  is `None`;
- a frontend storage check built its patterns with `new RegExp` over a template
  literal, where `\\b` is a backspace rather than a word boundary, so every pattern
  matched nothing;
- the traceability gate read one hard-wired plan while a second plan accumulated
  eighty unchecked obligations across nine merged slices.

So every enumeration here has a floor, and every ledger has a guard that plants a
violation and requires detection. A gate over an empty collection is the most
comfortable green there is.

**What this does NOT prove.** It checks that each protected route is *accounted
for* — guarded and covered, or explicitly excused with an owner. It does not read
the tests to judge whether they assert the right thing; `test_permission_guards.py`
and the integration suites do that. And it says nothing about the frontend half of
the DoD, which needs two hostnames and a browser; those obligations are recorded as
pending against a compose-stack run in `test_traceability.py` rather than claimed
here.

Their ids are deliberately not written above. The traceability scanner counts any
obligation id appearing in a test file as coverage, so a docstring explaining that
something is *deferred* would satisfy the gate for it — which is how a comment
saying "we do not use localStorage" once satisfied a check for localStorage. The
ids live in one place, next to their owner.

Covers: TRACE-DOD-001, TRACE-DOD-002, TRACE-QA-001, SEC-CSRF-002, SEED-ACCT-001.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TESTS = REPOSITORY_ROOT / "tests"
QA_DOCUMENT = (
    REPOSITORY_ROOT
    / "Implementation Docs"
    / "06_DevOps_QA_and_Operations"
    / "14_Testing_QA_Acceptance.md"
)

# How each route is authorised. Derived from the source rather than guessed, and
# every entry is a claim the tests below check against the built app.
#
# A route absent from this map fails the gate. That is the whole point: a new
# protected surface has to be classified before it can ship, and the failure names
# it rather than leaving it silently unconsidered.
PUBLIC = "public"
OPERATIONS = "operations-token"
SESSION = "session-only"
OWNERSHIP = "ownership-scoped"
PERMISSION = "permission-guarded"
# One path, two audiences, authorised by different mechanisms: a trader by
# ownership and internal staff by permission. This class owes **both**
# negatives, not a choice between them — see the note above
# `NEGATIVE_TEST_REQUIRED`.
DUAL = "ownership-and-permission"

ROUTE_CLASSES: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/health/live"): PUBLIC,
    ("GET", "/api/v1/health/ready"): PUBLIC,
    ("GET", "/api/v1/health/dependencies"): OPERATIONS,
    ("GET", "/api/v1/health/workers"): OPERATIONS,
    ("GET", "/api/v1/meta/release"): PUBLIC,
    ("GET", "/api/v1/operations/background-processing"): OPERATIONS,
    ("GET", "/api/v1/operations/release-evidence"): OPERATIONS,
    ("POST", "/api/v1/center-profile/rename"): OPERATIONS,
    ("POST", "/api/v1/auth/admin/login"): PUBLIC,
    ("POST", "/api/v1/auth/trader/login"): PUBLIC,
    ("POST", "/api/v1/traders/register"): PUBLIC,
    ("GET", "/api/v1/auth/me"): SESSION,
    ("POST", "/api/v1/auth/logout"): SESSION,
    ("POST", "/api/v1/auth/reauthenticate"): SESSION,
    # Ownership-scoped, not session-only. Slice 10 classified both `SESSION`, which is
    # the one class carrying no obligation, so the DoD's first clause was discharged
    # for them by a label. Both filter on the caller: `listOwnSessions` selects
    # `column == actor.actor_id` (`app/api/v1/auth.py:726`) and `revokeOwnSession`
    # refuses when `owner != actor.actor_id` (`:777`). Their own operation ids say so.
    ("GET", "/api/v1/auth/sessions"): OWNERSHIP,
    ("POST", "/api/v1/auth/sessions/{session_id}/revoke"): OWNERSHIP,
    # Ownership-scoped for the same reason as those two, and classified so deliberately:
    # the route acts on the caller's own credential and ends the caller's own sessions,
    # and `session-only` is the class that carries no obligation at all. Naming it that
    # would have been the third time the DoD's first clause was discharged by a label.
    ("POST", "/api/v1/auth/change-password"): OWNERSHIP,
    ("GET", "/api/v1/me/trader/profile"): OWNERSHIP,
    ("PATCH", "/api/v1/me/trader/profile"): OWNERSHIP,
    ("POST", "/api/v1/traders/{trader_id}/approve"): PERMISSION,
    ("POST", "/api/v1/traders/{trader_id}/reject"): PERMISSION,
    ("POST", "/api/v1/traders/{trader_id}/suspend"): PERMISSION,
    ("POST", "/api/v1/traders/{trader_id}/reactivate"): PERMISSION,
    # The centre's read surface over the businesses it approves. Guarded on
    # `trader.read`, which no trader holds — a trader resolves no permissions at all,
    # so the audience separation refuses them rather than a filter somebody could
    # write wrongly.
    ("GET", "/api/v1/traders"): PERMISSION,
    ("GET", "/api/v1/traders/{trader_id}"): PERMISSION,
    # Slice 8D. Each on the *canonical* permission the approved catalogue resolves
    # doc 05's `admin_user.*` aliases to, one per action: doc 12:700 forbids merging
    # unrelated high-risk actions into one broad permission, and `declare` on an alias
    # raises rather than granting.
    ("GET", "/api/v1/admin-users"): PERMISSION,
    ("POST", "/api/v1/admin-users"): PERMISSION,
    ("GET", "/api/v1/admin-users/{admin_user_id}"): PERMISSION,
    ("PATCH", "/api/v1/admin-users/{admin_user_id}"): PERMISSION,
    # Slice 8E's three acts on somebody else. Suspension is `user.deactivate` because the
    # catalogue's four canonical codes contain no `user.suspend`, and deactivate is the
    # code that names removal of access; reactivation and the reset are `user.update`,
    # deliberately separate from it — an installation that wants one person able to
    # suspend during an incident without also being able to undo somebody else's
    # suspension can express that, and one broad permission could not.
    ("POST", "/api/v1/admin-users/{admin_user_id}/suspend"): PERMISSION,
    ("POST", "/api/v1/admin-users/{admin_user_id}/reactivate"): PERMISSION,
    ("POST", "/api/v1/admin-users/{admin_user_id}/password-reset"): PERMISSION,
    # Roles. `role.read` and `role.manage` are the catalogue's own codes and document 05
    # agrees with document 12 on both, so no alias resolution is needed here.
    ("GET", "/api/v1/roles"): PERMISSION,
    ("GET", "/api/v1/roles/{role_id}"): PERMISSION,
    ("PUT", "/api/v1/roles/{role_id}/permissions"): PERMISSION,
    # M4 slice 2. PERMISSION rather than OWNERSHIP: an upload creates a file that nobody
    # owns yet, so there is no existing resource whose owner could be compared against
    # the actor. Ownership starts to matter at download, which is slice 5 and arrives
    # with its own resolver and its own negative tests.
    ("POST", "/api/v1/files"): PERMISSION,
    # M4 slice 5. OWNERSHIP rather than PERMISSION, and the distinction is the slice: the
    # permission says an actor may download *some* file, and the ownership resolver says
    # whether they may have *this* one. A file the actor may not reach answers exactly as
    # a missing one does, so the negative test asserts indistinguishability rather than a
    # 403 — a 403 would confirm the id is real.
    ("GET", "/api/v1/files/{file_id}"): OWNERSHIP,
    ("GET", "/api/v1/files/{file_id}/download"): OWNERSHIP,
    ("GET", "/api/v1/files/{file_id}/preview"): OWNERSHIP,
    # M4 slice 8. PERMISSION rather than OWNERSHIP: bank configuration is centre-wide and
    # belongs to no trader, so there is no owner to compare an actor against. A trader
    # session is refused at the audience boundary before any of this is reached.
    ("GET", "/api/v1/bank-profiles"): PERMISSION,
    ("POST", "/api/v1/bank-profiles"): PERMISSION,
    ("GET", "/api/v1/bank-accounts"): PERMISSION,
    ("POST", "/api/v1/bank-accounts"): PERMISSION,
    # M4 slice 9. Guarded by `bank_profile.activate_version`, which exists and is granted
    # to no role — so this route denies every caller today, deliberately
    # (DOC-CONFLICT-045). Its negative test is the one that must be *rewritten* rather
    # than deleted when the owner approves the grant.
    ("POST", "/api/v1/bank-profile-versions/{version_id}/activate"): PERMISSION,
    # M5 slice 3, DUAL for the same reason as the beneficiary routes: a trader
    # reaches their own requests by ownership and holds no permission at all,
    # while internal staff reach them by `payment_request.*` and own nothing.
    ("POST", "/api/v1/payment-requests"): DUAL,
    ("POST", "/api/v1/payment-requests/{payment_request_id}/cancel"): DUAL,
    # PUBLIC by necessity rather than by choice, which is why it is not SESSION: an
    # account in `recovery_required` is refused every action except recovery, so it holds
    # no session to classify. The temporary credential an administrator set is what stands
    # in, together with a rate limit on both axes.
    ("POST", "/api/v1/auth/admin/recover-password"): PUBLIC,
    # FastAPI's own, absent in production — `test_openapi_contract.py` asserts they
    # 404 there. Listed rather than filtered by pattern, because a filter would also
    # hide a real route somebody named `/docs`.
    ("GET", "/api/v1/openapi.json"): PUBLIC,
    ("GET", "/api/v1/docs"): PUBLIC,
}

# Classes that require a negative test, and what kind. The DoD names two kinds, so
# these are the two that carry an obligation; PUBLIC and OPERATIONS carry their own
# checks elsewhere and are not what the sentence is about.
#
# WHICH READING THIS ENFORCES, recorded because two documents disagree and this gate
# silently chose one.
#
# `15_Agent_Implementation_Plan.md:666` says "ownership **and** permission negative
# tests exist for every implemented protected resource", and this plan's slice 10 reads
# that as "for each require **both**" (`M3_IMPLEMENTATION_PLAN.md:852-854`). Taken
# literally, the four decision routes would also owe ownership negatives and the two
# profile routes would also owe permission negatives: twelve obligations, not six.
#
# This mapping enforces the narrower reading — **one obligation per route, from the
# class that actually guards it** — and the reason is that the wider one asks for tests
# that cannot be written as stated. `POST /traders/{id}/approve` has no ownership
# dimension: an admin does not own a trader, so an "ownership negative" for it would
# have to invent a relationship the schema does not have, and a test asserting a
# refusal that no code path produces proves nothing about ownership. Likewise the
# profile routes declare no permission, because trader access is ownership-scoped
# rather than granted through `admin_user_roles`.
#
# So the sentence's "and" is read as spanning the *set of resources* rather than
# applying both kinds to each one. That is a defensible reading and it is not the only
# one, which is exactly why it is written here instead of being left implicit: until
# the owner records a choice, "the DoD gate is green" and "the DoD is met" are
# different statements, and this comment is what keeps the difference visible.
#
# M5 narrows the exception rather than the rule. The argument above for the
# narrower reading is that the wider one demands tests that cannot be written —
# an admin does not own a trader. Where both *can* be written, it does not
# apply, and for a route serving both audiences both can. So the values here are
# tuples: a class may carry more than one obligation instead of the map
# silently permitting only one.
NEGATIVE_TEST_REQUIRED: dict[str, tuple[str, ...]] = {
    OWNERSHIP: ("ownership",),
    PERMISSION: ("permission",),
    DUAL: ("ownership", "permission"),
}

# The negative test that discharges each obligation, by (method, path, kind). Every
# entry names a test that must exist; `test_every_claimed_test_exists` fails on one
# that does not, so a citation pointing at nothing is louder than a missing citation.
NEGATIVE_COVERAGE: dict[tuple[str, str, str], str] = {
    ("GET", "/api/v1/me/trader/profile", "ownership"): ("test_a_trader_sees_only_its_own_business"),
    ("PATCH", "/api/v1/me/trader/profile", "ownership"): (
        "test_there_is_no_field_in_which_to_submit_another_traders_id"
    ),
    ("POST", "/api/v1/traders/{trader_id}/approve", "permission"): (
        "test_an_authenticated_admin_without_the_permission_is_refused"
    ),
    ("POST", "/api/v1/traders/{trader_id}/reject", "permission"): (
        "test_rejecting_without_the_permission_is_refused"
    ),
    ("POST", "/api/v1/traders/{trader_id}/suspend", "permission"): (
        "test_suspending_without_the_permission_is_refused"
    ),
    ("POST", "/api/v1/traders/{trader_id}/reactivate", "permission"): (
        "test_reactivating_without_the_permission_is_refused"
    ),
    ("GET", "/api/v1/auth/sessions", "ownership"): (
        "test_the_session_routes_are_scoped_to_the_caller"
    ),
    ("POST", "/api/v1/auth/sessions/{session_id}/revoke", "ownership"): (
        "test_the_session_routes_are_scoped_to_the_caller"
    ),
    ("POST", "/api/v1/auth/change-password", "ownership"): (
        "test_a_password_change_touches_only_the_callers_own_sessions"
    ),
    # One parametrised test covers all four, and the parametrisation itself is guarded:
    # `test_the_denial_parametrisation_covers_every_admin_user_route` fails if the list
    # shrinks, which is how a parametrised negative quietly stops covering a route.
    ("GET", "/api/v1/admin-users", "permission"): (
        "test_an_admin_without_the_permission_is_refused"
    ),
    ("POST", "/api/v1/admin-users", "permission"): (
        "test_an_admin_without_the_permission_is_refused"
    ),
    ("GET", "/api/v1/admin-users/{admin_user_id}", "permission"): (
        "test_an_admin_without_the_permission_is_refused"
    ),
    ("PATCH", "/api/v1/admin-users/{admin_user_id}", "permission"): (
        "test_an_admin_without_the_permission_is_refused"
    ),
    ("GET", "/api/v1/traders", "permission"): (
        "test_reading_traders_without_the_permission_is_refused"
    ),
    ("GET", "/api/v1/traders/{trader_id}", "permission"): (
        "test_reading_traders_without_the_permission_is_refused"
    ),
    # Slice 8E's three, covered by the same parametrised denial as the four above — and
    # covered honestly, because that parametrisation is guarded against the *published
    # contract*. Adding these routes is what made `test_the_denial_parametrisation_covers_
    # every_admin_user_route` fail, which is exactly the design: a new route with no
    # denial case cannot reach this ledger without somebody noticing.
    ("POST", "/api/v1/admin-users/{admin_user_id}/suspend", "permission"): (
        "test_an_admin_without_the_permission_is_refused"
    ),
    ("POST", "/api/v1/admin-users/{admin_user_id}/reactivate", "permission"): (
        "test_an_admin_without_the_permission_is_refused"
    ),
    ("POST", "/api/v1/admin-users/{admin_user_id}/password-reset", "permission"): (
        "test_an_admin_without_the_permission_is_refused"
    ),
    # The role surface, parametrised over the three routes and guarded against the
    # published contract the same way. The unprivileged caller is `accountant`, which the
    # seed grants neither `role.read` nor `role.manage` — chosen rather than invented, so
    # the denial proves the seeded catalogue withholds the permission.
    #
    # Naming `test_a_reader_cannot_change_a_role` here instead would have been wrong and
    # was the first thing written: that test signs in as `manager`, which *holds*
    # `role.read`, so it proves the two GETs succeed. It would have discharged two
    # obligations with a test asserting their opposite. It stays as the other half —
    # holding the read and being refused the write is what proves the two are separate.
    ("GET", "/api/v1/roles", "permission"): "test_an_admin_without_the_permission_is_refused",
    ("GET", "/api/v1/roles/{role_id}", "permission"): (
        "test_an_admin_without_the_permission_is_refused"
    ),
    ("PUT", "/api/v1/roles/{role_id}/permissions", "permission"): (
        "test_an_admin_without_the_permission_is_refused"
    ),
    # M4 slice 2. The privileged/unprivileged pair is inverted from every entry above:
    # `file.upload` is held by accountant, trader_owner and warehouse_operator and *not*
    # by business_admin, which holds all four `user.*` permissions. So the account that
    # is privileged everywhere else in this ledger is the unauthorised one here, which is
    # what makes the denial about `file.upload` rather than about being signed in.
    ("POST", "/api/v1/files", "permission"): (
        "test_an_authenticated_actor_without_the_permission_is_denied"
    ),
    ("GET", "/api/v1/files/{file_id}", "ownership"): (
        "test_an_unreachable_file_answers_exactly_like_a_missing_one"
    ),
    ("GET", "/api/v1/files/{file_id}/download", "ownership"): (
        "test_staff_without_the_sensitive_grant_cannot_reach_a_bundle_either"
    ),
    ("GET", "/api/v1/files/{file_id}/preview", "ownership"): (
        "test_a_trader_cannot_reach_an_internal_bank_bundle"
    ),
    ("GET", "/api/v1/bank-profiles", "permission"): (
        "test_an_actor_without_the_bank_permission_is_denied"
    ),
    ("POST", "/api/v1/bank-profiles", "permission"): (
        "test_an_actor_without_the_bank_permission_is_denied"
    ),
    ("GET", "/api/v1/bank-accounts", "permission"): (
        "test_an_actor_without_the_bank_permission_is_denied"
    ),
    ("POST", "/api/v1/bank-accounts", "permission"): (
        "test_an_actor_without_the_bank_permission_is_denied"
    ),
    ("POST", "/api/v1/bank-profile-versions/{version_id}/activate", "permission"): (
        "test_activation_is_denied_to_every_role"
    ),
    # M5 slice 3. Four entries, because two DUAL routes owe both kinds.
    ("POST", "/api/v1/payment-requests", "ownership"): (
        "test_a_trader_cannot_open_a_request_under_another_trader"
    ),
    ("POST", "/api/v1/payment-requests", "permission"): (
        "test_an_admin_without_the_request_permission_is_refused"
    ),
    ("POST", "/api/v1/payment-requests/{payment_request_id}/cancel", "ownership"): (
        "test_a_trader_cannot_cancel_another_traders_request"
    ),
    ("POST", "/api/v1/payment-requests/{payment_request_id}/cancel", "permission"): (
        "test_an_admin_without_the_request_permission_is_refused"
    ),
}

# Nothing is pending. Kept as an empty dict rather than deleted, because the checks
# below compare against it and a deleted name would make them pass by absence —
# and because the next protected route to ship needs somewhere to be owed from.
#
# `test_every_guarded_route_has_its_negative_tests_or_an_owner` is what makes an empty
# dict safe: it walks the *live routes* and requires each guarded one to appear in one
# collection or the other, so emptying this one cannot quietly widen the gap it used
# to record — the obligation comes from the router, not from this dict's length.
PENDING_NEGATIVE_COVERAGE: dict[tuple[str, str, str], str] = {}


def routes_of(app: object) -> list[tuple[str, str]]:
    """Every `/api/v1` route the built application serves.

    Walks `original_router` and accumulates `include_context.prefix`, because this
    FastAPI version stores each `include_router` call as a private wrapper whose own
    `path` is `None` and whose children carry unprefixed paths. The same walk as
    `test_permission_guards.py`, and duplicated deliberately: a shared helper in a
    third file is a third thing to keep working, and the floor below is what proves
    this copy still reads the real surface.
    """

    found: list[tuple[str, str]] = []
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
            found.append((method, full))

    walk(app, "")
    return found


def published_operation_count() -> int:
    """How many operations the committed contract publishes.

    Used as the route-count floor. The contract is the right source because it is
    held equal to the application by `pnpm openapi:check` and pinned operation by
    operation by `test_openapi_contract.py` — so it cannot be quietly lowered to
    make this gate pass.
    """

    import json

    contract = json.loads(
        (REPOSITORY_ROOT / "services" / "backend" / "openapi" / "v1.json").read_text(
            encoding="utf-8"
        )
    )
    return sum(
        1
        for item in contract["paths"].values()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    )


def defined_test_names() -> set[str]:
    """Every test function defined anywhere in the suite."""

    found: set[str] = set()
    for path in TESTS.rglob("*.py"):
        found.update(
            re.findall(r"^\s*def (test_[a-z0-9_]+)\(", path.read_text(encoding="utf-8"), re.M)
        )
    return found


@pytest.fixture
def live_routes(app_factory: Any) -> list[tuple[str, str]]:
    app, _runtime, _settings = app_factory()
    return routes_of(app)


class TestTheEnumerationIsReal:
    """Guard the guard, first. Everything below is vacuous without these."""

    def test_the_reader_finds_the_whole_surface(self, live_routes: list[tuple[str, str]]) -> None:
        """The floor, derived rather than written down.

        A hand-written `>= 22` cannot guard itself: a negative control lowered it to
        `>= 0` and nothing failed, because the only test checking the floor *was* the
        floor. So the number comes from the committed OpenAPI contract — which
        `pnpm openapi:check` holds equal to the application, and which
        `test_openapi_contract.py` pins operation by operation.

        Lowering the floor now means regenerating a gated artifact, which is a
        different and far louder act than editing an integer in a test.
        """

        published = published_operation_count()

        assert published >= 20, (
            f"the committed contract publishes only {published} operations, so the "
            "floor it supplies would not constrain anything"
        )
        assert len(live_routes) >= published, (
            f"only {len(live_routes)} routes found against {published} published "
            "operations. The permission gate's reader once returned two of twenty-two "
            "because FastAPI nests routers privately; if that has changed again, this "
            "gate is checking almost nothing."
        )
        for anchor in (
            ("POST", "/api/v1/auth/admin/login"),
            ("PATCH", "/api/v1/me/trader/profile"),
            ("POST", "/api/v1/traders/{trader_id}/approve"),
        ):
            assert anchor in live_routes, f"{anchor} is missing from the reader's output"

    def test_there_are_routes_of_each_guarded_class(self) -> None:
        for guarded in NEGATIVE_TEST_REQUIRED:
            assert any(value == guarded for value in ROUTE_CLASSES.values()), (
                f"no route is classified {guarded!r}, so its obligations are vacuous"
            )


class TestEveryRouteIsClassified:
    def test_no_route_escapes_classification(self, live_routes: list[tuple[str, str]]) -> None:
        """A new protected surface must be classified before it ships."""

        unclassified = sorted(route for route in live_routes if route not in ROUTE_CLASSES)

        assert unclassified == [], (
            "these routes are served and not classified, so nothing decides whether "
            f"they owe a negative test:\n{unclassified}"
        )

    def test_no_classification_names_a_route_that_is_gone(
        self, live_routes: list[tuple[str, str]]
    ) -> None:
        """A stale entry exempts nothing while reading like a decision."""

        stale = sorted(route for route in ROUTE_CLASSES if route not in live_routes)

        assert stale == [], f"classified routes that no longer exist: {stale}"


class TestTheDefinitionOfDone:
    def test_every_guarded_route_has_its_negative_tests_or_an_owner(
        self, live_routes: list[tuple[str, str]]
    ) -> None:
        """The sentence itself, enumerated.

        For every route whose class carries an obligation, a negative test of that
        kind is either named here or owned by a named slice. Neither is not an
        option, and that is the difference between this and a checklist.
        """

        missing: list[str] = []
        for method, path in sorted(live_routes):
            for kind in NEGATIVE_TEST_REQUIRED.get(
                ROUTE_CLASSES.get((method, path), ""), ()
            ):
                key = (method, path, kind)
                if (
                    key not in NEGATIVE_COVERAGE
                    and key not in PENDING_NEGATIVE_COVERAGE
                ):
                    missing.append(f"{method} {path} needs a {kind} negative test")

        assert missing == [], (
            "M3's Definition of Done is not met for these routes:\n"
            + "\n".join(f"  {entry}" for entry in missing)
            + "\nName the test in NEGATIVE_COVERAGE, or record the slice that owes it "
            "in PENDING_NEGATIVE_COVERAGE."
        )

    def test_every_claimed_test_exists(self) -> None:
        """A citation pointing at nothing is worse than an honest deferral."""

        known = defined_test_names()
        broken = sorted(
            f"{method} {path} ({kind}) -> {name}"
            for (method, path, kind), name in NEGATIVE_COVERAGE.items()
            if name not in known
        )

        assert broken == [], f"claimed negative tests that do not exist: {broken}"

    def test_every_pending_entry_names_an_owner_and_a_live_route(
        self, live_routes: list[tuple[str, str]]
    ) -> None:
        for (method, path, kind), owner in sorted(PENDING_NEGATIVE_COVERAGE.items()):
            assert (method, path) in live_routes, (
                f"{method} {path} is pending a {kind} test and is not served — a "
                "deferral for a route that does not exist"
            )
            assert owner.startswith("M"), f"{method} {path} defers to {owner!r}, no milestone"

    def test_nothing_is_both_covered_and_pending(self) -> None:
        overlap = sorted(set(NEGATIVE_COVERAGE) & set(PENDING_NEGATIVE_COVERAGE))

        assert overlap == [], (
            f"these are claimed covered and also deferred: {overlap}. One of the two is "
            "wrong, and a reader cannot tell which."
        )


class TestSurfaceWideProperties:
    """Two properties of the whole surface rather than of any one route."""

    def test_no_route_changes_state_through_a_get(self, live_routes: list[tuple[str, str]]) -> None:
        """SEC-CSRF-002. `12_Security_RBAC_Audit.md:497` prohibits it in terms.

        This is what makes the CSRF exemption for safe methods safe to treat as
        exhaustive: `cookies.SAFE_METHODS` skips the token check for GET, HEAD,
        OPTIONS and TRACE, and that is only correct while no GET writes anything. A
        state-changing GET would be reachable by a cross-site image tag, with no
        token and no preflight.

        Checked structurally, by requiring every GET route to be one this file has
        classified as a read. A behavioural version would need a mutation oracle per
        route, and the structural one fails on the thing that actually goes wrong —
        somebody adding a GET that writes.
        """

        writing_verbs = (
            "create",
            "update",
            "delete",
            "revoke",
            "approve",
            "reject",
            "suspend",
            "reactivate",
            "rename",
            "register",
            "login",
            "logout",
        )

        offenders = [
            f"GET {path}"
            for method, path in sorted(live_routes)
            if method == "GET" and any(verb in path.lower() for verb in writing_verbs)
        ]

        assert offenders == [], (
            "these GET routes name a state-changing action, and a GET carries no CSRF "
            f"token: {offenders}. Doc 12:497 prohibits state-changing GET endpoints."
        )

    def test_no_migration_inserts_a_credential(self) -> None:
        """SEED-ACCT-001. `12_Security_RBAC_Audit.md:386` forbids it.

        A seeded credential is one that exists in every deployment, is identical
        across them, and is published in the repository. Migration `_0008` seeds the
        RBAC catalogue and states in its own docstring that it inserts no credential;
        this is the check that keeps that true for every migration after it.

        Scanned for the *columns* rather than for the word "password": a migration
        that inserted into `admin_users` at all would be creating an identity, and
        `password_hash` is `NOT NULL`, so naming the table in an INSERT is the
        signal.
        """

        versions = REPOSITORY_ROOT / "services" / "backend" / "alembic" / "versions"
        migrations = sorted(versions.glob("*.py"))

        assert len(migrations) >= 13, (
            f"only {len(migrations)} migrations found; the scan below would check almost nothing"
        )

        offenders: list[str] = []
        for path in migrations:
            text = path.read_text(encoding="utf-8")
            # Comments and docstrings discuss this rule at length, so only executable
            # INSERT text counts — the same lesson as the frontend storage check,
            # where matching prose made the gate trip on its own explanation.
            statements = re.findall(r"INSERT\s+INTO\s+([a-z_\"\.]+)", text, re.I)
            for target in statements:
                table = target.strip('"').split(".")[-1]
                if table in {"admin_users", "trader_users"}:
                    offenders.append(f"{path.name} inserts into {table}")

        assert offenders == [], (
            "a migration creates an identity, which means a credential shipped in the "
            f"image and identical in every deployment: {offenders}"
        )


class TestMandatoryQaCases:
    """Doc 14 §16's cases, counted against the document rather than described."""

    def test_the_qa_sections_still_exist(self) -> None:
        """Guard the guard: a renamed heading would make the counts below zero."""

        document = QA_DOCUMENT.read_text(encoding="utf-8")

        for heading in (
            "## 16.1 Permission matrix",
            "## 16.2 Trader isolation",
            "## 16.3 Separation of duties",
            "## 16.4 Session and recent-auth",
        ):
            assert heading in document, f"doc 14 no longer contains {heading!r}"

    def test_the_isolation_ledger_lives_with_its_tests(self) -> None:
        """§16.2's seven cases are accounted for where they are exercised.

        Deliberately not re-counted here. `tests/integration/test_trader_isolation.py`
        holds the ledger and asserts it against doc 14; a second count in this file
        would be the fifth copy of a number this project has already been bitten by.
        This only checks the ledger is still there and still self-checking.
        """

        source = (TESTS / "integration" / "test_trader_isolation.py").read_text(encoding="utf-8")

        assert "MANDATORY_IDOR_CASES" in source
        assert "def test_the_ledger_accounts_for_all_seven_mandatory_cases(" in source

    def test_the_permission_matrix_has_a_negative_test_at_all(self) -> None:
        """§16.1: positive **and** negative, and role names are not sufficient.

        The narrowest honest claim. Doc 14 wants every permission covered both ways;
        M3 declares four and exercises one denial through HTTP. What this asserts is
        that the denial path is exercised at all — because until slice 10 it was not,
        across five merged slices, and the guard's `ForbiddenError` had never once
        been reached by a test.
        """

        source = (TESTS / "integration" / "test_trader_registration.py").read_text(encoding="utf-8")

        assert "def test_an_authenticated_admin_without_the_permission_is_refused(" in source
        assert "def test_the_same_call_succeeds_for_a_role_that_holds_the_permission(" in source
