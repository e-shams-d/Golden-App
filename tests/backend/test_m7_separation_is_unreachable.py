"""M7 slice 6A. Two prohibitions the milestone must prove, and neither needs a bank file.

Slice 6 is the M7 Definition of Done gate and it has four obligations. Two of them — the full
chain from a sent export, and the check that this milestone owes nothing — cannot be written until
the export exists, and G-1 has not been answered. The other two need nothing that is not already
merged, so they are here and the remaining two stay in `PENDING` under 6B's name. Slice 5's split
set the precedent in this milestone; M3's slice 8 set it in the repository.

Their ids are deliberately not written above. The traceability scanner counts **any** occurrence
of an obligation id in a test file as that file citing it, so naming the two this slice does *not*
discharge would have marked them covered — while the sentence naming them said the opposite. That
has now been the failure eleven times; the only reliable defence is to describe an absent
obligation rather than to name it.

**Both live in `tests/backend`, and that is the whole reason they can be trusted.** In
`tests/integration` a missing PostgreSQL turns a prohibition into a skip, and a skipped
prohibition reads exactly like a satisfied one from the exit code.
`15_Agent_Implementation_Plan.md:983` asks for break-glass absence to be *tested*; a test that
silently does not run is not one.

**Neither of these asserts what the code chose.** `TRACE-DOD-014` reads the approved policy and
the live application; `TRACE-DOD-015` reads the mapped models and the route table. Both would
fail on a change that a reviewer looking at a diff would plausibly wave through — which is the
only kind of gate worth adding at this point in a milestone.

Covers: TRACE-DOD-014, TRACE-DOD-015.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from test_permission_guards import declared_permissions, routes_of

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPOSITORY_ROOT / "services" / "backend" / "app"

FINALIZE = "payment_batch_version.finalize"
APPROVE = "payment_batch_version.approve"
REJECT = "payment_batch_version.reject"

# `FINANCIAL_INTEGRITY_BASELINE.md` §5, POL-005 Approved: break-glass is disabled for Phase 1A
# with "no activation, grants, endpoints, flags or runtime bypasses". Five prohibitions.
#
# **Three of them already have gates and this file does not repeat them** — it names them, and
# `test_every_named_gate_exists` fails if one is renamed or deleted. Re-asserting them here would
# have been cheap and wrong: two tests for one property drift apart, and the day somebody relaxes
# the real one the copy keeps the suite green.
#
# The two without a gate are `endpoints` and `runtime bypasses`, and they are what this file adds.
BREAK_GLASS_PROHIBITIONS: dict[str, str] = {
    "grants": (
        "tests/backend/test_high_risk_grants.py"
        "::test_the_forbidden_code_exists_and_is_the_one_policy_disables"
    ),
    "flags": (
        "tests/backend/test_seeded_flags_match_the_model.py"
        "::test_no_break_glass_flag_is_seeded_in_any_spelling"
    ),
    "activation": (
        "tests/backend/test_rbac_seed_matches_catalogue.py"
        "::TestSeedShape::test_break_glass_is_seeded_with_no_grants"
    ),
    "endpoints": "test_no_route_declares_a_break_glass_permission, in this file",
    "runtime bypasses": "test_no_module_reads_a_break_glass_switch, in this file",
}


def _python_sources() -> list[Path]:
    return sorted(path for path in BACKEND.rglob("*.py") if "__pycache__" not in path.parts)


def test_every_named_gate_exists() -> None:
    """The corpus check, and M6 is why it is here.

    M6 found five registry entries left out of the one tuple its catalogue gate iterated, hiding a
    false claim for two milestones behind a green gate. A dictionary that names three tests in
    other files has exactly that shape: rename one and this file goes on reporting that
    break-glass is covered.

    Node ids are parsed rather than executed — running them would make this test a duplicate of
    them, and what needs checking is that they are still there under these names.
    """

    missing: list[str] = []
    for prohibition, reference in sorted(BREAK_GLASS_PROHIBITIONS.items()):
        if ", in this file" in reference:
            continue
        path, _, node = reference.partition("::")
        source = REPOSITORY_ROOT / path
        if not source.exists():
            missing.append(f"{prohibition}: {path} does not exist")
            continue
        names = {
            element.name
            for element in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
            if isinstance(element, ast.FunctionDef | ast.ClassDef)
        }
        wanted = node.split("::")[-1]
        if wanted not in names:
            missing.append(f"{prohibition}: {path} has no {wanted}")

    assert missing == [], (
        "a break-glass prohibition points at a gate that is no longer there, so this file would "
        f"report coverage it does not have: {missing}"
    )


def test_no_route_declares_a_break_glass_permission(app_factory: Any) -> None:
    """`TRACE-DOD-014`, the `endpoints` half. §5: no endpoint, for Phase 1A.

    Read from the mounted application rather than from a list of routes, so a route added
    tomorrow is covered the moment it exists.

    The control matters as much as the assertion: a reader that stopped seeing routes would make
    this pass over an application that had grown a break-glass endpoint, which is the shape M5's
    gate was caught in — a prohibition asserted over an empty set passes and reads like a
    prohibition that holds.
    """

    routes = routes_of(app_factory()[0])
    assert len(routes) > 20, (
        f"only {len(routes)} routes were found; the reader has stopped seeing them and this "
        "prohibition would be asserted over almost nothing"
    )

    offenders = {
        f"{method} {path}": sorted(
            code for code in declared_permissions(route) if code.startswith("break_glass.")
        )
        for method, path, route in routes
        if any(code.startswith("break_glass.") for code in declared_permissions(route))
    }

    assert offenders == {}, (
        "these routes declare a break-glass permission, which POL-005 disables for Phase 1A "
        f"with no endpoint: {offenders}"
    )


def test_no_module_reads_a_break_glass_switch() -> None:
    """`TRACE-DOD-014`, the `runtime bypasses` half — the one with no other gate.

    §5 forbids a runtime bypass, and a runtime bypass does not look like `break_glass.activate`.
    It looks like `if settings.allow_break_glass:` or `os.environ.get("BREAK_GLASS")`, added by
    somebody solving a real operational problem at two in the morning.

    So this reads the source rather than the route table: any `break_glass`/`breakglass` spelling
    in `app/` outside the two places it legitimately belongs — the permission catalogue, which
    must list the codes because M0 catalogues them, and `high_risk_grants`, which exists to
    *refuse* the grant.

    Text, not AST. An AST scan would have to decide what counts as a switch, and the failure being
    prevented is precisely a form nobody anticipated. A false positive here costs one line in
    `PERMITTED`; a false negative costs the property.
    """

    permitted = {
        BACKEND / "security" / "permission_catalogue.py",
        BACKEND / "security" / "high_risk_grants.py",
        BACKEND / "commands" / "role_permissions.py",
        BACKEND / "db" / "models" / "configuration.py",
    }

    found: list[str] = []
    for source in _python_sources():
        if source in permitted:
            continue
        text = source.read_text(encoding="utf-8").lower()
        if "break_glass" in text or "breakglass" in text:
            found.append(str(source.relative_to(REPOSITORY_ROOT)))

    assert found == [], (
        "these modules mention break-glass and are not one of the four that may. POL-005 "
        "disables it for Phase 1A with no runtime bypass, and a bypass is a name in a module "
        f"rather than a row in a catalogue: {found}"
    )


def test_every_permitted_module_still_mentions_break_glass() -> None:
    """The other direction, because a stale exemption absorbs the next real one.

    If `high_risk_grants` stopped naming `break_glass.activate`, the grant would no longer be
    refused **and** the test above would still pass, because an exemption for a module that no
    longer mentions it silently permits the next module that does. The same shape as
    `test_every_approved_addition_is_still_an_addition` in the schema gates.
    """

    stale = [
        str(path.relative_to(REPOSITORY_ROOT))
        for path in (
            BACKEND / "security" / "permission_catalogue.py",
            BACKEND / "security" / "high_risk_grants.py",
            BACKEND / "commands" / "role_permissions.py",
            BACKEND / "db" / "models" / "configuration.py",
        )
        if "break_glass" not in path.read_text(encoding="utf-8").lower()
    ]

    assert stale == [], (
        "these modules are exempted from the break-glass scan and no longer mention it, so the "
        f"exemption is now a licence for whatever moves into them: {stale}"
    )


def test_no_route_can_both_finalize_and_decide(app_factory: Any) -> None:
    """`TRACE-DOD-015`, over the whole route table rather than the two routes involved.

    `FINANCIAL_INTEGRITY_BASELINE.md` §5 compares two *recorded actors*, and that comparison
    happens after both acts. A route that performed both would make the comparison meaningless
    before it ran: the finalizer and the approver would be the same person by construction, and
    the CHECK constraint would refuse every such call — turning a security property into an
    outage nobody could explain.

    Asserted over every route because the danger is not the two routes that exist today. It is
    the convenience endpoint somebody adds later — "finalize and approve in one step, for batches
    the manager prepared themselves" — which is a sentence that sounds reasonable right up to the
    moment it is written down.
    """

    routes = routes_of(app_factory()[0])
    assert len(routes) > 20, (
        f"only {len(routes)} routes were found; the reader has stopped seeing them"
    )

    offenders = {
        f"{method} {path}": sorted(declared_permissions(route))
        for method, path, route in routes
        if FINALIZE in declared_permissions(route)
        and declared_permissions(route) & {APPROVE, REJECT}
    }

    assert offenders == {}, (
        "these routes declare both the finalize grant and a decision grant, so one call would "
        f"make one actor the finalizer and the approver of the same version: {offenders}"
    )


def test_no_single_function_calls_both_the_finalize_and_the_approve_command() -> None:
    """`TRACE-DOD-015`'s other half, one layer below the route table.

    A route is not the only place the two can be joined. A worker, a scheduled job or a service
    helper could call `finalize_version` and then `approve_version` in the same transaction, and
    no route table would show it.

    **Per function, not per module**, and the first version of this test got that wrong.
    `app/api/v1/payment_batches.py` calls both — it mounts the finalize route and the approve
    route, which is exactly what it should do. A module-level scan called that a violation, which
    is the shape of a gate that has to be relaxed on its first real run and is then trusted less
    forever. What matters is whether **one code path** can do both.

    Read as a call graph rather than as text: a function that merely names both in a comment is
    not calling them.
    """

    offenders: list[str] = []
    for source in _python_sources():
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for scope in ast.walk(tree):
            if not isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            called = {
                node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
                for node in ast.walk(scope)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute | ast.Name)
            }
            if {"finalize_version", "approve_version"} <= called:
                offenders.append(f"{source.relative_to(REPOSITORY_ROOT)}::{scope.name}")

    assert offenders == [], (
        "these functions call both the finalize and the approve command, so one code path can "
        f"make one actor both the finalizer and the approver: {offenders}"
    )


@pytest.mark.parametrize(
    "constraint",
    [
        "ck_batch_approvals_approver_is_not_finalizer",
        "ck_batch_approvals_approver_is_not_preparer",
    ],
)
def test_the_separation_constraints_are_still_on_the_model(constraint: str) -> None:
    """`TRACE-DOD-015`'s schema half, in `tests/backend` on purpose.

    `tests/integration/test_batch_approval.py` proves these refuse a real insert, and that is the
    stronger proof — but it needs PostgreSQL, and without one it **skips**. A milestone whose
    separation guard is proved only by a test that can skip has a guard nobody would notice
    losing.

    So this asserts the constraints are on the mapped model, which needs no database and cannot
    skip. Deleting one fails here immediately and fails the integration test wherever a database
    exists.
    """

    import app.db.models  # noqa: F401  # registers every mapped table
    from app.db.base import Base

    names = {
        item.name
        for item in Base.metadata.tables["batch_approvals"].constraints
        if item.name is not None
    }

    assert constraint in names, (
        f"batch_approvals has no {constraint!r} constraint. FINANCIAL_INTEGRITY_BASELINE.md §5 "
        "requires the separation rule to be enforced by a database-enforceable guard, and G-2 "
        "records that relaxing the preparer half is the owner's decision rather than a side "
        f"effect of a refactor. Present: {sorted(names)}"
    )
