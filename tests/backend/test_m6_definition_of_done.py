"""M6's Definition of Done, gated — the half that must not become a skip.

`15_Agent_Implementation_Plan.md:897`:

> M6 is complete when an accountant can produce an exact immutable batch version ready for
> manager review and all row-level bank data is frozen in relational snapshots.

Two clauses. The journey half is `tests/integration/test_m6_journey.py`, which needs a database.
**This file needs none**, and that is the point: in `tests/integration` a missing PostgreSQL turns
the milestone's central prohibition into a skip, and a skipped gate is a green gate. M5's
Definition-of-Done gate lives in `tests/backend` for the same reason and this one follows it.

What it asserts:

- **No manager-only permission is required to reach a finalized version.** M6 builds the object
  approval binds to; M7 builds the decision. A batch route that declared `.approve` would mean an
  accountant could not finalize without the grant that approves — which is
  `FINANCIAL_INTEGRITY_BASELINE.md` §5 defeated at the routing layer, before any comparison of
  actors happens.
- **The converse, which is M6's own risk:** no *request-level* route or command has gained a
  manager-only permission while M6 was adding batch-level authority. Discharged by asserting M5's
  gate still holds over the current route table, which is a claim about this milestone rather
  than about the last one.
- **`PENDING` contains no M6 obligation.**

The manager-only set is **derived from the permission catalogue**, not listed here. M5's gate
established that: a hard-coded list is a second place for the truth to live, and the failure it
would hide is a fourth manager permission added to the catalogue and to nothing else.

Covers: TRACE-DOD-012, SEC-BATCH-004, TRACE-M6-001.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, ClassVar

import pytest

# M5's fixtures, reused rather than reimplemented: the manager-only set is **derived from the
# permission catalogue** there, and a second derivation is a second thing to be wrong about which
# permissions are manager-only.
#
# `noqa: F811` on the two that appear as test parameters below. ruff reads a fixture name used as
# a parameter as a redefinition of the import; pytest resolves it through the fixture registry,
# and the import is what puts it there. Suppressed here with the reason rather than in the ruff
# config, which would also hide a real redefinition somewhere else.
from test_m5_definition_of_done import (  # noqa: F401
    blocks,
    catalogue_text,
    manager_only,
    request_prefix,
)
from test_permission_guards import declared_permissions, guards_admitting_only, routes_of
from test_traceability import PENDING

BATCH_PREFIX = "/api/v1/payment-batches"

# The commands M6 built, by module. Named so that a module added later without an entry here
# fails the completeness check at the bottom rather than escaping the scan.
M6_COMMAND_MODULES = ("payment_batch.py",)

# The one manager-only permission an M6 command may name, by the owner's 2026-08-25 decision under
# DOC-CONFLICT-056. Spelled here rather than derived from the catalogue, because the exception is a
# decision about *this* permission: a derived rule would widen itself the moment another
# manager-only grant arrived.
CANCEL_APPROVED = "payment_batch.cancel_approved"

# Batch command modules a later milestone owns, which the manager-only prohibition therefore does
# **not** apply to. `payment_batch_approval.py` names `payment_batch_version.approve` because
# approving is what it does.
#
# Listed rather than skipped by pattern. The completeness check at the bottom of this file asserts
# that every `*batch*.py` under `app/commands` appears in one of these two tuples, so a module
# added later still fails until somebody decides which one it belongs in. A regex that let
# anything containing "approval" through would have been the exemption nobody re-reads.
LATER_MILESTONE_BATCH_COMMAND_MODULES = ("payment_batch_approval.py",)

# The six routes M6 mounted, by name. Two tests below need this set for opposite reasons — one
# asserts every one of them exists, the other asserts none of them is manager-gated — and it was
# written out inline in the first when there was only one caller.
#
# It is a *fixed* list on purpose, and that matters more now than when it was written. M7 mounts
# `approve` and `reject` under the same prefix and they **are** manager-gated, correctly. Had the
# prohibition below kept iterating every batch route, the choice on the day M7 arrived would have
# been to delete a true gate or to weaken it. Naming M6's own six keeps it proving exactly what it
# was written to prove — that the actor who finalizes is not, by routing, an actor who may
# approve — while leaving M7 free to add routes that are.
M6_BATCH_PATHS: tuple[str, ...] = (
    f"{BATCH_PREFIX}/preview",
    BATCH_PREFIX,
    f"{BATCH_PREFIX}/{{batch_id}}",
    f"{BATCH_PREFIX}/{{batch_id}}/versions",
    f"{BATCH_PREFIX}/{{batch_id}}/versions/{{version_id}}/finalize",
    f"{BATCH_PREFIX}/{{batch_id}}/cancel",
)


def batch_routes(app_factory: Any) -> list[tuple[str, str, object]]:
    """Every route under the batch prefix, with its route object.

    Derived from the mounted application rather than from a list, so a route added in M7 is
    covered the moment it exists. `routes_of` is `test_permission_guards`'s reader, reused rather
    than reimplemented — a second reader is a second thing to be wrong about what "declared"
    means, and `owned_or_permitted` hides its permissions in a closure.
    """

    found = [
        (method, path, route)
        for method, path, route in routes_of(app_factory()[0])
        if path.startswith(BATCH_PREFIX)
    ]
    assert found, (
        f"no routes under {BATCH_PREFIX}; either the router is unmounted or the reader has "
        "stopped seeing them — and this file would then assert nothing"
    )
    return found


def test_the_batch_surface_is_found_at_all(app_factory: Any) -> None:
    """The control. Without it, a broken reader makes every assertion below vacuous.

    M5's gate learned this: a prohibition asserted over an empty set passes, and reads exactly
    like a prohibition that holds.
    """

    routes = batch_routes(app_factory)
    paths = {path for _method, path, _route in routes}

    # The ones M6 built, by name. A count would pass on any six.
    for expected in M6_BATCH_PATHS:
        assert expected in paths, f"{expected} is not mounted; {sorted(paths)}"


def test_no_batch_route_requires_a_manager_only_permission(
    app_factory: Any,
    manager_only: frozenset[str],  # noqa: F811
) -> None:
    """`TRACE-DOD-012`. M6 stops at "ready for manager review".

    `15_Agent_Implementation_Plan.md:901` opens M7 as "Exact Manager Approval, Final Export, and
    Mark Sent", so every M6 route must be reachable by an accountant. A batch route declaring
    `payment_batch_version.approve` would mean finalization required the approval grant — and
    then the actor who finalizes is necessarily an actor who may approve, which is
    `FINANCIAL_INTEGRITY_BASELINE.md` §5 defeated at the routing layer, before any comparison of
    actors could happen.

    Asserted over the declared permissions rather than over role membership: a route could be
    reachable today because one accountant happens to hold a manager role, and that is an
    accident of seeding rather than a property of the route.

    **Scoped to `M6_BATCH_PATHS`, and the scoping is the point.** M7 slice 1 mounts `approve` and
    `reject` under this same prefix, and those routes *must* declare a manager-only permission —
    that is the separation rule working, not breaking it. Iterating every batch route would have
    made this gate fail on the correct change, and the two ways out of that would have been to
    delete it or to add an exemption list nobody re-reads. Naming M6's own six keeps the claim
    exact: **finalization** must stay reachable by an accountant.
    """

    m6_routes = [
        (method, path, route)
        for method, path, route in batch_routes(app_factory)
        if path in M6_BATCH_PATHS
    ]
    # The control the sibling test above provides for the whole surface, repeated for this
    # subset: a filter that matched nothing would make the prohibition below vacuous, which is
    # the exact failure this file's first test exists to prevent.
    assert len(m6_routes) >= len(M6_BATCH_PATHS), (
        f"only {len(m6_routes)} of M6's {len(M6_BATCH_PATHS)} paths matched; the filter has "
        "stopped seeing them and this assertion would prove nothing"
    )

    # **`guards_admitting_only`, not `declared_permissions`**, and G-5 is what forced the
    # distinction. The cancel route admits a caller holding *either* cancellation grant and lets
    # `authority_for_cancelling` choose on the batch's status, so it names `cancel_approved`
    # without an accountant ever needing it — they reach the handler on `cancel_draft` alone.
    # Reading the flat declared set here would fail on a route that keeps this gate's property
    # perfectly, and the two ways out of that are to delete the gate or to exempt the route: both
    # give up the claim.
    #
    # The prohibition is unchanged for every guard naming one permission, which is all of the
    # others: for those the two readings are identical.
    offenders = {
        f"{method} {path}": [sorted(group) for group in blocked]
        for method, path, route in m6_routes
        if (blocked := guards_admitting_only(route, manager_only))
    }

    assert offenders == {}, (
        "these M6 routes require a manager-only permission, so an accountant cannot reach them "
        f"and the actor who finalizes is an actor who may approve: {offenders}"
    )


def test_a_guard_offering_only_manager_grants_is_caught(
    manager_only: frozenset[str],  # noqa: F811
) -> None:
    """The control for the reading above, and the reason it is not simply weaker.

    `guards_admitting_only` deliberately tolerates a manager-only permission *alongside* an
    accountant's, because that is an alternative rather than a requirement. The failure that
    tolerance could hide is a guard offering a choice between two manager-only grants — a caller
    holding neither is refused whichever way they turn, so the accountant is locked out exactly as
    if one had been named alone.

    Built here rather than mounted, because the application does not contain such a route and
    should not: the claim is about the *reader*, and a reader that stopped catching this would
    make the prohibition above pass over the one shape it cannot see.

    The three cases are asserted together on purpose. A control that only proved the catch would
    be satisfied by a reader that flagged everything.
    """

    restricted = sorted(manager_only)
    assert len(restricted) >= 2, (
        f"fewer than two manager-only permissions in the catalogue ({restricted}), so the "
        "offending shape below cannot be built and this control proves nothing"
    )
    approve, reject = restricted[0], restricted[1]
    accountant_grant = "payment_batch.cancel_draft"
    assert accountant_grant not in manager_only, (
        "the catalogue now makes cancel_draft manager-only, which would make the tolerated case "
        "below indistinguishable from the caught one"
    )

    both_restricted = _route_with_guards([{approve, reject}])
    assert guards_admitting_only(both_restricted, manager_only) == [{approve, reject}], (
        "a guard whose every alternative is manager-only was not caught; the prohibition above "
        "would then pass over a route no accountant can reach"
    )

    mixed = _route_with_guards([{accountant_grant, approve}])
    assert guards_admitting_only(mixed, manager_only) == [], (
        "a guard offering an accountant grant as an alternative was flagged, which would fail the "
        "prohibition on the cancel route that keeps its property"
    )

    conjunction = _route_with_guards([{accountant_grant}, {approve}])
    assert guards_admitting_only(conjunction, manager_only) == [{approve}], (
        "two separate guards compose with AND, so a manager-only one among them is required and "
        "must be caught however many others there are"
    )


def _guard_holding(permissions: set[str]) -> Any:
    """A dependency shaped the way `permission_alternatives` reads them.

    **Real closures**, because the reader walks `call.__closure__` and inspects each cell for an
    approved permission string. A stand-in object with a `permissions` attribute would exercise a
    reader this codebase does not have, and `__closure__` cannot be assigned onto a function — so
    the cells are made the only way they can be: by capturing one free variable each.
    """

    captured = sorted(permissions)
    assert 1 <= len(captured) <= 2, "the control needs guards of one or two permissions"

    if len(captured) == 1:
        (only,) = captured

        def one() -> str:  # pragma: no cover - inspected, never called
            return only

        call: Any = one
    else:
        first, second = captured

        def two() -> tuple[str, str]:  # pragma: no cover - inspected, never called
            return first, second

        call = two

    class _Dependency:
        pass

    dependency = _Dependency()
    dependency.call = call  # type: ignore[attr-defined]
    return dependency


def _route_with_guards(groups: list[set[str]]) -> Any:
    class _Dependant:
        dependencies: ClassVar[list[Any]] = [_guard_holding(group) for group in groups]

    class _Route:
        dependant: ClassVar[Any] = _Dependant()

    return _Route()


def test_no_request_level_route_gained_a_manager_only_permission(
    app_factory: Any,
    manager_only: frozenset[str],  # noqa: F811
    request_prefix: str,  # noqa: F811
) -> None:
    """`SEC-BATCH-004`. The converse, and M6's own risk.

    M5's gate asserted this over M5's route table. The claim here is about **this** milestone: M6
    added batch-level authority, and the way that goes wrong is a manager permission drifting onto
    the request surface — a request route that needed `.approve` would put a trader's own request
    behind the grant that approves bank files.

    Re-derived rather than delegated to M5's test passing, because "the other test is green" is a
    claim about that test's inputs and not about the current route table.
    """

    offenders = {
        f"{method} {path}": sorted(declared_permissions(route) & manager_only)
        for method, path, route in routes_of(app_factory()[0])
        if path.startswith(request_prefix) and declared_permissions(route) & manager_only
    }

    assert offenders == {}, (
        f"these request-level routes require a manager-only permission: {offenders}. M6 adds "
        "batch authority and must not move manager authority onto the request surface."
    )


def test_no_m6_command_declares_a_manager_only_permission(
    manager_only: frozenset[str],  # noqa: F811
) -> None:
    """The same prohibition one layer down, read from the source.

    A route is not the only place a permission can be required: a command could check one
    directly, and the failure being prevented is precisely a check the route table cannot see.

    **One manager-only permission is now allowed here, and it is named.** The owner's 2026-08-25
    decision under DOC-CONFLICT-056 made cancelling an *approved* batch require
    `payment_batch.cancel_approved` — a manager-only grant that `payment_batch.py` must be able to
    name, because `authority_for_cancelling` chooses it from the batch's status. Everything this
    gate was actually written about is untouched: `payment_batch_version.approve` and every other
    manager-only permission stay prohibited outright, so a finalization path that required the
    grant that approves still fails here.

    The companion test below is what keeps the exception from becoming a hole.
    """

    commands = Path(__file__).resolve().parents[2] / "services" / "backend" / "app" / "commands"
    modules = [commands / name for name in M6_COMMAND_MODULES]
    prohibited = manager_only - {CANCEL_APPROVED}
    assert prohibited, (
        f"the only manager-only permission in the catalogue is {CANCEL_APPROVED}, so subtracting "
        "it leaves this scan with nothing to look for and the prohibition asserts nothing"
    )

    problems: list[str] = []
    for module in modules:
        assert module.exists(), f"{module} is missing; M6's command module moved"
        text = module.read_text(encoding="utf-8")
        for permission in sorted(prohibited):
            if permission in text:
                problems.append(f"{module.name} names {permission}")

    assert problems == [], (
        "an M6 command names a manager-only permission, so finalization would require the grant "
        f"that approves: {problems}"
    )


def test_the_cancellation_permission_is_never_named_inside_a_command_function() -> None:
    """What makes the exception above narrow rather than a hole.

    `payment_batch.cancel_approved` exists in `payment_batch.py` exactly once, as the module-level
    constant `CANCEL_APPROVED_OPERATION`, and reaches the decision through
    `authority_for_cancelling` — which returns *which* permission the transition needs and leaves
    the comparison to `cancel_batch`, against `command.held_permissions`. So no function body
    contains the literal, and that absence is the assertable form of "no command hard-codes a
    permission check on itself".

    A function that spelled the string inline would be a check the route table cannot see and the
    scan above no longer catches — which is the precise shape this gate was written to forbid, one
    permission later.

    **An AST walk over string constants, skipping docstrings**, for the reason this repository has
    now hit eight times: a prose explanation of a prohibition collides with a text scan for it, and
    the prose is what loses.
    """

    module = (
        Path(__file__).resolve().parents[2]
        / "services" / "backend" / "app" / "commands" / "payment_batch.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))

    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    assert functions, "no functions parsed out of payment_batch.py; the walk sees nothing"

    offenders = sorted(
        node.name
        for node in functions
        if any(
            isinstance(literal, ast.Constant)
            and literal.value == CANCEL_APPROVED
            and literal is not _docstring_node(node)
            for literal in ast.walk(node)
        )
    )
    assert offenders == [], (
        f"{offenders} name {CANCEL_APPROVED} inline. The permission belongs in "
        "`CANCEL_APPROVED_OPERATION` and reaches a caller's grants through "
        "`authority_for_cancelling`; a literal inside a function is a permission check the route "
        "table cannot see."
    )

    # The control. Without it an AST walk that found no constants at all would pass, which is the
    # same green as a prohibition that holds.
    module_level = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == CANCEL_APPROVED
    ]
    assert module_level, (
        f"{CANCEL_APPROVED} appears nowhere in payment_batch.py, so the walk above is looking for "
        "something that is not there and would pass however the module were written"
    )


def _docstring_node(function: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST | None:
    """The function's docstring expression, so the walk above can skip it.

    A docstring is an `ast.Constant` like any other, so a function explaining why it must not name
    a permission would be caught for explaining it.
    """

    first = function.body[0] if function.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        return first.value
    return None


def test_every_m6_command_module_is_in_the_scan(
    manager_only: frozenset[str],  # noqa: F811
) -> None:
    """A module added without an entry above fails here rather than escaping the check.

    Derived from the batch routes' handlers would be tighter, but a command module reached only
    by a worker has no route — so the list is explicit and this is what keeps it honest.
    """

    del manager_only
    commands = Path(__file__).resolve().parents[2] / "services" / "backend" / "app" / "commands"
    present = {
        path.name
        for path in commands.glob("*.py")
        if path.name != "__init__.py" and "batch" in path.name
    }

    accounted = set(M6_COMMAND_MODULES) | set(LATER_MILESTONE_BATCH_COMMAND_MODULES)

    assert present == accounted, (
        "the batch command modules and this file's lists have diverged. Every module must be in "
        "M6_COMMAND_MODULES, where the manager-only prohibition applies, or in "
        "LATER_MILESTONE_BATCH_COMMAND_MODULES, where it deliberately does not.\n"
        f"  present, not accounted for: {sorted(present - accounted)}\n"
        f"  accounted for, not present: {sorted(accounted - present)}"
    )


M6_PREFIXES = ("BATCH", "ATTEMPT", "ALLOC", "SPLIT", "FINAL")


def test_pending_holds_no_m6_obligation() -> None:
    """`TRACE-M6-001`. Nothing is owed for M6; this reads the ledger.

    **Matched by full obligation id against the plan, not by prefix.** A prefix filter would be
    the M4 defect `obligations_stated_by` exists to prevent: `SVC-FINAL-001` and `DB-FINAL-001`
    share a prefix with nothing, and `AUD-BATCH-002` shares one with obligations M7 owns. So the
    ids are read from M6's own plan and the ledger is checked against exactly those.
    """

    plan = (
        Path(__file__).resolve().parents[2]
        / "docs"
        / "handoff"
        / "M6_IMPLEMENTATION_PLAN.md"
    )
    text = plan.read_text(encoding="utf-8")

    # The "What proves it" sections, which is where the plan states an obligation. The same
    # section `test_traceability.py` parses, so the two cannot disagree about what M6 claimed.
    proves = re.findall(r"### What proves it\n(.*?)(?=\n### |\n## |\Z)", text, re.S)
    assert proves, "no 'What proves it' section found in the M6 plan; its layout changed"

    stated = set()
    for section in proves:
        stated.update(re.findall(r"\b[A-Z]+-[A-Z0-9]+-\d+\b", section))
    assert stated, "the M6 plan states no obligations, so this gate would assert nothing"

    owed = sorted(stated & set(PENDING))
    assert owed == [], (
        f"these M6 obligations are still in PENDING: {owed}. Each is a slice that claimed to "
        "prove something and did not, or a ledger entry nobody removed."
    )


def test_the_ledger_check_would_notice_a_prefix_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control on the test above: it must be matching ids, not prefixes.

    A prefix filter over `BATCH`/`FINAL`/`ALLOC` would pass for M6 today *and* would silently
    absorb M7's `AUD-BATCH-004` the moment somebody adds it to `PENDING` — reporting M6 clean by
    counting an obligation that is not M6's. So this puts a fabricated M7-shaped entry in the
    ledger and asserts the check above stays green, which is only true of an id-matched check.
    """

    monkeypatch.setitem(PENDING, "AUD-BATCH-009", "M7 — not M6's, and must not be read as M6's")
    test_pending_holds_no_m6_obligation()

    # And the converse: a genuine M6 id in the ledger must fail.
    monkeypatch.setitem(PENDING, "SVC-FINAL-001", "fabricated, to prove the check bites")
    with pytest.raises(AssertionError, match="SVC-FINAL-001"):
        test_pending_holds_no_m6_obligation()
