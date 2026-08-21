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

import re
from pathlib import Path
from typing import Any

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
from test_permission_guards import declared_permissions, routes_of
from test_traceability import PENDING

BATCH_PREFIX = "/api/v1/payment-batches"

# The commands M6 built, by module. Named so that a module added later without an entry here
# fails the completeness check at the bottom rather than escaping the scan.
M6_COMMAND_MODULES = ("payment_batch.py",)


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

    # The five M6 built, by name. A count would pass on any five.
    for expected in (
        f"{BATCH_PREFIX}/preview",
        BATCH_PREFIX,
        f"{BATCH_PREFIX}/{{batch_id}}",
        f"{BATCH_PREFIX}/{{batch_id}}/versions",
        f"{BATCH_PREFIX}/{{batch_id}}/versions/{{version_id}}/finalize",
        f"{BATCH_PREFIX}/{{batch_id}}/cancel",
    ):
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
    """

    offenders = {
        f"{method} {path}": sorted(declared_permissions(route) & manager_only)
        for method, path, route in batch_routes(app_factory)
        if declared_permissions(route) & manager_only
    }

    assert offenders == {}, (
        "these M6 routes require a manager-only permission, so an accountant cannot reach them "
        f"and the actor who finalizes is an actor who may approve: {offenders}"
    )


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
    directly. Scanned as text rather than through the route table, because the failure being
    prevented is precisely a check the route table cannot see.
    """

    commands = Path(__file__).resolve().parents[2] / "services" / "backend" / "app" / "commands"
    modules = [commands / name for name in M6_COMMAND_MODULES]

    problems: list[str] = []
    for module in modules:
        assert module.exists(), f"{module} is missing; M6's command module moved"
        text = module.read_text(encoding="utf-8")
        for permission in sorted(manager_only):
            if permission in text:
                problems.append(f"{module.name} names {permission}")

    assert problems == [], (
        "an M6 command names a manager-only permission, so finalization would require the grant "
        f"that approves: {problems}"
    )


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

    assert present == set(M6_COMMAND_MODULES), (
        "the batch command modules and this file's list have diverged.\n"
        f"  present, not scanned: {sorted(present - set(M6_COMMAND_MODULES))}\n"
        f"  scanned, not present: {sorted(set(M6_COMMAND_MODULES) - present)}"
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
