"""M5's Definition of Done, the half that cannot be proved by calling something.

`15_Agent_Implementation_Plan.md:818` ends the milestone's DoD with a negative: a trader
reaches `eligible_for_batching` **"without any manager approval at request level"**. The
journey half is an integration test. This is the other half, and it is structural.

**Nothing here makes a request.** No `TestClient`, no database, no sign-in, no `403`. The
only execution is importing the application, and that import is load-bearing: `declare()`
raises `UnknownPermission` at import, so a misspelled permission fails this file's own
collection rather than being quietly absent from a set.

**And it deliberately lives in `tests/backend`, not `tests/integration`.** The integration
suite skips when no PostgreSQL is configured. A skipped gate is a green gate, and the one
property the milestone's DoD states as a prohibition must not be able to disappear because
a developer had no database.

**What this can and cannot prove.** The role matrix at `12_Security_RBAC_Audit.md:876-904`
distinguishes `A` (approves) from `X` (acts), and that distinction has no representation in
the permission layer at all — `manager` and `business_admin` hold the identical
`trader.approve` code. So a permission-set gate can prove "no manager-only permission is
required at request level"; it cannot prove "no manager approval" in the document's fuller
sense. Stated here rather than left for a reader to over-read.

A second limit, same spirit: `owned_or_permitted` declares the trader-side permission and
deliberately never checks it, because no trader session resolves permissions at all
(`app/security/actor.py:113-118`). So the disjointness below is a statement about what
routes *declare*. A manager-only id arriving as the trader argument would fail this gate
while being harmless — the right direction to err, and worth predicting rather than
discovering.

Covers: TRACE-DOD-008.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from test_permission_guards import UNGUARDED_ROUTES, declared_permissions, routes_of

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = REPOSITORY_ROOT / "docs" / "governance" / "permission_catalog.yaml"
BACKEND = REPOSITORY_ROOT / "services" / "backend"
ROUTES_MODULE = BACKEND / "app" / "api" / "v1" / "payment_requests.py"
COMMANDS_MODULE = BACKEND / "app" / "commands" / "payment_request.py"

# `      domain.action:` at the catalogue's permission depth, and the lines under it.
_CODE = re.compile(r"^ {6}([a-z_]+\.[a-z_.]+):$", re.M)
_LIST = re.compile(r"^\s*default_roles:\s*\[([^\]]*)\]", re.M)
_STATUS = re.compile(r"^\s*status:\s*(\S+)", re.M)

# Rows the owner has not settled. Excluded explicitly and asserted by equality below: an
# owner approving one of these must change this gate deliberately rather than silently.
PROPOSED = frozenset({"proposed_pending_owner_decision"})

# The permissions a request route may declare that `manager` can also hold, with the reason.
# Recorded by **equality**, not merely permitted: a new manager-touched permission on a
# request route fails until a person writes down why it is not manager approval.
MANAGER_TOUCHED: dict[str, str] = {
    "payment_request.read": (
        "manager holds it alongside accountant, business_admin and read_only_auditor — "
        "matrix `R`. Reading a request is not approving it, and a gate keyed on 'manager "
        "appears in default_roles' would wrongly fail here."
    ),
    "payment_request.cancel": (
        "`conditional_roles: {manager: exception_policy_only}`. DOC-CONFLICT-002 (POL-002) "
        "is the one place manager authority touches a request, and it is an exception "
        "policy rather than the ordinary path. Asserted in shape below, not just allowed."
    ),
}


@pytest.fixture(scope="module")
def catalogue_text() -> str:
    return CATALOGUE.read_text(encoding="utf-8")


def _blocks(text: str) -> dict[str, str]:
    """Each permission code mapped to the lines beneath it.

    Parsed with a regular expression rather than a YAML loader, for the reason
    `test_high_risk_grants.py` gives: a loader is a dependency this test would then share
    with the code under test, and the question here is what the approved file says.
    """

    found: dict[str, str] = {}
    matches = list(_CODE.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        found[match.group(1)] = text[match.end() : end]
    return found


def _default_roles(block: str) -> frozenset[str]:
    match = _LIST.search(block)
    if match is None:
        return frozenset()
    return frozenset(part.strip() for part in match.group(1).split(",") if part.strip())


def _conditional_roles(block: str) -> dict[str, str]:
    if "conditional_roles:" not in block:
        return {}
    after = block.split("conditional_roles:", 1)[1]
    pairs: dict[str, str] = {}
    for line in after.splitlines():
        if not line.strip():
            continue
        stripped = line.strip()
        if ":" not in stripped or stripped.endswith(":"):
            break
        key, _, value = stripped.partition(":")
        if key.strip() in {"constraints", "default_roles", "status", "notes"}:
            break
        pairs[key.strip()] = value.strip()
    return pairs


@pytest.fixture(scope="module")
def blocks(catalogue_text: str) -> dict[str, str]:
    parsed = _blocks(catalogue_text)
    # Guard the guard. An empty or near-empty parse makes every set operation below
    # trivially true, and a disjointness assertion against nothing passes forever.
    assert len(parsed) >= 80, (
        f"only {len(parsed)} permission codes were parsed from the catalogue. The pattern "
        "no longer matches how it writes them, and everything in this file is now "
        "comparing against almost nothing."
    )
    return parsed


@pytest.fixture(scope="module")
def manager_only(blocks: dict[str, str]) -> frozenset[str]:
    """Permissions the manager holds and nobody else, excluding unsettled rows."""

    codes: set[str] = set()
    for code, block in blocks.items():
        status = _STATUS.search(block)
        if status is not None and status.group(1) in PROPOSED:
            continue
        if _default_roles(block) == frozenset({"manager"}) and not _conditional_roles(block):
            codes.add(code)
    return frozenset(codes)


@pytest.fixture
def request_routes(app_factory: Any, request_prefix: str) -> list[tuple[str, str, object]]:
    """The live route table, built the way `test_permission_guards.py` builds it.

    Through `app_factory` rather than `create_app` directly, so this gate walks the same
    application that gate walks — and so a route added next month is in scope the moment it
    is mounted. A hand-written route list would freeze at today's surface, which is the
    failure mode this whole file exists to prevent one level up.
    """

    app, _runtime, _settings = app_factory()
    return _request_scoped(routes_of(app), request_prefix)


@pytest.fixture
def request_prefix(app_factory: Any) -> str:
    """The mounted prefix, derived from the live route table.

    Not `router.prefix` — that is empty, because the mount prefix is applied where the router
    is included, and a first version of this fixture read it and got `""`. The consequence was
    quiet: the prefix half of the classification below matched nothing, the permission half
    carried the whole gate, and the synthetic manager-only probe was not even classified as
    request-scoped. A falsy prefix disabling half a union is exactly the kind of silence this
    file exists to refuse.

    So it is derived: the common parent of every route that declares a `payment_request.*`
    permission. Nothing to keep in step with the router, and it cannot be empty while those
    routes exist — which the guard below asserts.
    """

    app, _runtime, _settings = app_factory()
    paths = [
        path
        for _method, path, route in routes_of(app)
        if any(name.startswith("payment_request.") for name in declared_permissions(route))
    ]
    assert paths, "no route declares a payment_request permission, so no prefix can be derived"
    common = paths[0]
    for path in paths[1:]:
        while not path.startswith(common):
            common = common[: common.rfind("/")]
    return common.rstrip("/")


def _request_scoped(
    routes: list[tuple[str, str, object]], prefix: str
) -> list[tuple[str, str, object]]:
    """Routes acting on payment requests, by two derivations unioned.

    The prefix rule alone misses a request action mounted somewhere else; the permission
    rule alone misses a request route that declares nothing. Union, so neither gap is the
    gate's blind spot.
    """

    scoped = []
    for method, path, route in routes:
        by_prefix = prefix and prefix in path
        by_permission = any(
            name.startswith("payment_request.") for name in declared_permissions(route)
        )
        if by_prefix or by_permission:
            scoped.append((method, path, route))
    return scoped


# --- Guard the guard, before anything is asserted about the sets --------------------------


def test_the_request_surface_is_found_at_all(
    request_routes: list[tuple[str, str, object]],
) -> None:
    """An empty left side makes disjointness true forever, and looks exactly like success."""

    assert len(request_routes) >= 10, (
        f"only {len(request_routes)} request-scoped routes were found. M5 mounts ten on the "
        "payment-request router alone, so the reader has stopped seeing them."
    )
    pairs = {(method, path) for method, path, _ in request_routes}
    for anchor in (
        ("POST", "/api/v1/payment-requests"),
        ("GET", "/api/v1/payment-requests"),
        ("POST", "/api/v1/payment-requests/{payment_request_id}/mark-eligible-for-batching"),
        ("POST", "/api/v1/payment-requests/{payment_request_id}/submit"),
    ):
        assert anchor in pairs, f"{anchor} is missing from the request surface"


def test_the_manager_only_set_is_real(manager_only: frozenset[str]) -> None:
    """Derived, and pinned by equality.

    Equality rather than non-emptiness because the set is what the whole gate turns on. The
    catalogue has eleven permissions granted to nobody, and `retention.approve` is described
    as manager authority — seeded as written it becomes a fourth entry here. That must be a
    loud failure asking a person to look, not a silent widening of what this gate polices.
    """

    assert manager_only == frozenset(
        {
            "payment_batch_version.approve",
            "payment_batch_version.reject",
            "payment_batch_version.invalidate_approval",
        }
    ), sorted(manager_only)


def test_the_seed_grants_the_manager_only_set_to_manager_alone(
    manager_only: frozenset[str],
) -> None:
    """"Manager-only per catalogue but not per seed" must not pass.

    The catalogue is the approved statement and the migration is what ships. A permission
    the document reserves to the manager but the seed hands to an accountant would make this
    gate protect a property the running system does not have.
    """

    seed = (
        BACKEND
        / "alembic"
        / "versions"
        / "20260801_0008_seed_rbac_catalogue.py"
    ).read_text(encoding="utf-8")

    for code in sorted(manager_only):
        holders = set(re.findall(rf'\("([a-z_]+)", "{re.escape(code)}"\)', seed))
        assert holders == {"manager"}, f"the seed grants {code} to {sorted(holders)}"


def test_the_reader_sees_a_permission_declared_either_way() -> None:
    """Both declaration shapes reach `declared_permissions`, including the two-name one.

    `owned_or_permitted` keeps both names in its closure **by convention**, and its own
    comment says a name the closure does not carry is a name the gate cannot see. If somebody
    refactors it to close over a tuple, this fails loudly instead of assertion A quietly
    checking an empty set.
    """

    from app.api.v1.auth import requires
    from app.api.v1.payment_requests import owned_or_permitted
    from app.security.permissions import declare

    # Under `/api/v1`, because `routes_of` returns only routes at that prefix — its docstring
    # records that an earlier version of it found every endpoint and then filtered them all
    # out for exactly this reason.
    probe = APIRouter(prefix="/api/v1/probe")

    @probe.post("/single", dependencies=[requires(declare("payment_request.review"))])
    def single() -> None: ...

    # `owned_or_permitted` returns the `Depends` itself, so it is a default here rather than
    # wrapped in another `Depends` — and rather than written inside `Annotated`, which is how
    # the real module spells it. The `Annotated` form does not work *in this file*: it has
    # `from __future__ import annotations`, so the annotation reaches FastAPI as a string and
    # is evaluated against module globals, where a callable imported inside a test function
    # does not exist. The dependency then silently is not registered and the probe reports an
    # empty set — which is precisely the false pass this probe exists to prevent, so it is
    # worth the two lines to say why the shapes differ.
    @probe.post("/dual")
    def dual(
        scope: Any = owned_or_permitted("payment_request.read_own", "payment_request.read"),
    ) -> None: ...

    probe_app = FastAPI()
    probe_app.include_router(probe)
    seen = {path: declared_permissions(route) for _method, path, route in routes_of(probe_app)}

    assert seen["/api/v1/probe/single"] == {"payment_request.review"}
    assert seen["/api/v1/probe/dual"] == {"payment_request.read_own", "payment_request.read"}


def test_the_whole_pipeline_reports_a_manager_only_request_route(
    manager_only: frozenset[str], request_prefix: str
) -> None:
    """The negative control, permanent rather than performed once.

    This is the most important test in the file. TRACE-DOD-008 is a negative property, and a
    negative property is trivially satisfied by machinery that does nothing — in a repository
    whose recorded history is "complete mechanism with no caller", five times in M3 alone. So
    a synthetic route that *should* be reported is run through the real classification and the
    real intersection, and the gate must report it.
    """

    from app.api.v1.auth import requires
    from app.security.permissions import declare

    offending = APIRouter(prefix=request_prefix)

    @offending.post(
        "/{payment_request_id}/approve-as-manager",
        dependencies=[requires(declare("payment_batch_version.approve"))],
    )
    def approve() -> None: ...

    probe_app = FastAPI()
    probe_app.include_router(offending)

    scoped = _request_scoped(routes_of(probe_app), request_prefix)
    assert scoped, "the synthetic route was not classified as request-scoped"
    found = {
        name
        for _method, _path, route in scoped
        for name in declared_permissions(route) & manager_only
    }
    assert found == {"payment_batch_version.approve"}


# --- A, B, C, D: what the declarations say -------------------------------------------------


def test_no_request_route_declares_a_manager_only_permission(
    request_routes: list[tuple[str, str, object]], manager_only: frozenset[str]
) -> None:
    """`TRACE-DOD-008`, the whole of it in one assertion.

    Batch approval is a manager's job from M6 onward, so this rule will be pressed against
    with real motivation. The failure names the route and the permission, because "something
    is wrong" is not actionable at the moment somebody is adding a check they believe in.
    """

    offenders = sorted(
        f"{method} {path} declares {sorted(declared_permissions(route) & manager_only)}"
        for method, path, route in request_routes
        if declared_permissions(route) & manager_only
    )

    assert offenders == [], (
        "these request-level routes require a manager-only permission, and the M5 "
        "Definition of Done says a request reaches `eligible_for_batching` without any "
        "manager approval:\n" + "\n".join(offenders)
    )


def test_the_manager_touched_surface_is_exactly_what_is_recorded(
    request_routes: list[tuple[str, str, object]], blocks: dict[str, str]
) -> None:
    """Not banned — recorded. Two permissions a manager can hold appear on request routes.

    Equality, so a third one fails until somebody writes down why it is not manager approval.
    A gate that merely banned `manager` anywhere in `default_roles` would fail on
    `payment_request.read`, which is a manager reading a request rather than approving one.
    """

    touched: set[str] = set()
    for _method, _path, route in request_routes:
        for name in declared_permissions(route):
            block = blocks.get(name)
            if block is None:
                continue
            if "manager" in _default_roles(block) or "manager" in _conditional_roles(block):
                touched.add(name)

    assert touched == set(MANAGER_TOUCHED), (
        "the set of manager-touched permissions on request routes changed. Each one needs a "
        f"recorded reason it is not manager approval.\nfound: {sorted(touched)}\n"
        f"recorded: {sorted(MANAGER_TOUCHED)}"
    )


def test_cancellation_keeps_manager_authority_conditional(blocks: dict[str, str]) -> None:
    """The one place manager authority touches a request, asserted in shape.

    `payment_request.cancel` gives the manager an `exception_policy_only` condition and no
    place in `default_roles`. Promoting it would make manager approval part of the ordinary
    cancellation path, which is the thing POL-002 settled deliberately — so a set operation
    must not be what decides it.
    """

    block = blocks["payment_request.cancel"]

    assert "manager" not in _default_roles(block), _default_roles(block)
    assert _conditional_roles(block).get("manager") == "exception_policy_only", (
        _conditional_roles(block)
    )


def test_no_request_route_is_allowlisted_out_of_permission_guarding(
    request_routes: list[tuple[str, str, object]],
) -> None:
    """`UNGUARDED_ROUTES` is the one door a request route could leave through.

    It has no payment-request entry today. If one appeared, every assertion above would keep
    passing while the route required nothing at all — which is a stronger failure than
    requiring the wrong thing.
    """

    escaped = sorted(
        f"{method} {path}"
        for method, path, _route in request_routes
        if (method, path) in UNGUARDED_ROUTES
    )

    assert escaped == [], (
        "these request-level routes are allowlisted out of permission guarding:\n"
        + "\n".join(escaped)
    )


# --- The blind spot the declarations cannot cover ------------------------------------------
#
# `declared_permissions` walks closure cells. The enforcement itself is a comparison inside
# the guard body — `if required not in actor.permissions` — and a bare literal there is a
# code-object constant, not a cell. So this, written inline in a guard, is invisible to every
# assertion above:
#
#     if "payment_batch_version.approve" in actor.permissions: ...
#
# The module being policed documents the hazard in its own source: "a name the closure does
# not carry is a name the gate cannot see." The scans below are why that sentence is not also
# a description of this gate.


def _parse(path: Path) -> ast.Module:
    """Parse, and fail loudly rather than skip.

    A scanner that swallows `SyntaxError` reports nothing for the file it could not read,
    which is indistinguishable from reporting that the file is clean.
    """

    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as error:  # pragma: no cover - a parse failure is the finding
        pytest.fail(f"{path} did not parse, so it was not scanned: {error}")


def _strings_outside_docstrings(tree: ast.Module) -> set[str]:
    """Every string constant that is not a docstring.

    Docstrings are excluded deliberately. `app/commands/payment_request.py` already contains
    the prose claim "nothing manager-only is consulted here", and a gate satisfiable by the
    comment it exists to replace proves only that somebody wrote the comment.
    """

    documented: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
        ):
            text = ast.get_docstring(node, clean=False)
            if text is not None:
                documented.add(text)

    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in documented
    }


def test_no_request_module_names_a_manager_only_permission_in_source(
    manager_only: frozenset[str],
) -> None:
    """The literal a closure walk cannot see, in either the routes or the commands.

    Compared against the catalogue's ids rather than a pattern: a regular expression for
    "looks like a manager permission" would either miss a rename or fire on a comment.
    """

    offenders = []
    for path in (ROUTES_MODULE, COMMANDS_MODULE):
        found = _strings_outside_docstrings(_parse(path)) & manager_only
        offenders.extend(f"{path.name} contains the literal {name!r}" for name in sorted(found))

    assert offenders == [], (
        "a manager-only permission appears as a string in the request surface, where the "
        "route table cannot see it:\n" + "\n".join(offenders)
    )


def test_no_guard_tests_membership_against_a_literal_permission() -> None:
    """`if "..." in actor.permissions` — the exact shape that evades the route table.

    A *name* on the left is fine and is how the real guard is written: `required` is bound
    from `declare(...)`, so the route table sees it. A string constant on the left is a
    permission requirement that exists only in a function body.
    """

    offenders = []
    for path in (ROUTES_MODULE, COMMANDS_MODULE):
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.Compare):
                continue
            if not any(isinstance(op, ast.In | ast.NotIn) for op in node.ops):
                continue
            for comparator in node.comparators:
                if (
                    isinstance(comparator, ast.Attribute)
                    and comparator.attr in {"permissions", "role_snapshot", "roles"}
                    and isinstance(node.left, ast.Constant)
                ):
                    offenders.append(
                        f"{path.name}:{node.lineno} tests {node.left.value!r} against "
                        f".{comparator.attr}"
                    )

    assert offenders == [], (
        "these compare a literal against an actor's permissions or roles, so the "
        "requirement is invisible to the route table:\n" + "\n".join(offenders)
    )


def test_no_request_module_names_a_role(blocks: dict[str, str]) -> None:
    """Role-name evasion. `if "manager" in actor.role_snapshot` keys on no permission at all.

    Without this, every assertion above is bypassed by spelling the authority as a role
    rather than as a grant.

    The role list is the union of every `default_roles` entry and every `conditional_roles`
    key across the catalogue. A first version matched `^ {4}(\\w+):$` and collected
    `permissions`, `sections` and `source_refs` — the catalogue's own top-level keys — which
    would have made the scan below compare against three words that are not roles.
    """

    roles: set[str] = set()
    for block in blocks.values():
        roles |= set(_default_roles(block))
        roles |= set(_conditional_roles(block))

    # Guard the guard: an empty or wrong role list makes this assertion vacuous.
    assert {"manager", "accountant", "trader_owner"} <= roles, sorted(roles)

    offenders = []
    for path in (ROUTES_MODULE, COMMANDS_MODULE):
        found = _strings_outside_docstrings(_parse(path)) & roles
        offenders.extend(f"{path.name} names the role {name!r}" for name in sorted(found))

    assert offenders == [], (
        "a role name appears as a string in the request surface, which is authority the "
        "permission catalogue cannot see:\n" + "\n".join(offenders)
    )


def test_no_command_can_read_a_permission_at_all() -> None:
    """The strongest form available: commands are handed an actor that has no permissions.

    `AuditActor` carries no permission set, so a command that only ever sees one cannot read
    a permission by accident. `ActorContext` does carry them, and a command signature
    mentioning it would be the change that makes the whole prohibition unenforceable — so the
    signature is what is asserted, not the absence of a lookup somebody could add later.
    """

    tree = _parse(COMMANDS_MODULE)

    annotations = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "ActorContext"
    }
    assert annotations == set(), (
        "app/commands/payment_request.py mentions ActorContext. Commands receive an "
        "AuditActor, which has no permissions field; handing them a context that does would "
        "make TRACE-DOD-008's command half unprovable."
    )

    wrong = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        for argument in node.args.args + node.args.kwonlyargs:
            if argument.arg != "actor":
                continue
            annotation = argument.annotation
            if not (isinstance(annotation, ast.Name) and annotation.id == "AuditActor"):
                shown = ast.unparse(annotation) if annotation is not None else "nothing"
                wrong.append(f"{node.name} annotates actor as {shown}")

    assert wrong == [], "\n".join(wrong)


def test_no_command_imports_the_permission_machinery() -> None:
    """Nothing in the command layer reaches for the modules that resolve authority."""

    forbidden = {
        "app.security.permissions",
        "app.security.permission_catalogue",
        "app.security.high_risk_grants",
    }
    offenders = [
        f"{COMMANDS_MODULE.name}:{node.lineno} imports {node.module}"
        for node in ast.walk(_parse(COMMANDS_MODULE))
        if isinstance(node, ast.ImportFrom) and node.module in forbidden
    ]

    assert offenders == [], "\n".join(offenders)


def test_the_source_scanners_work_in_both_directions(manager_only: frozenset[str]) -> None:
    """Guard the guard, for the scans. Absent machinery satisfies a prohibition perfectly.

    Both directions, because a scanner that flagged everything would pass the sabotage tests
    and fail nothing else until somebody wrote a docstring.
    """

    approve = sorted(manager_only)[0]

    sabotage = (
        "def guard(actor):\n"
        f'    if "{approve}" in actor.permissions:\n'
        "        pass\n"
    )
    caught = ast.parse(sabotage)
    assert approve in _strings_outside_docstrings(caught)
    literal_tests = [
        node
        for node in ast.walk(caught)
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant)
    ]
    assert literal_tests, "the membership-test scanner would not have seen the sabotage"

    excused = ast.parse(f'def guard(actor):\n    """{approve} is not consulted here."""\n')
    assert approve not in _strings_outside_docstrings(excused), (
        "the scanner counts a docstring as a declaration, so the prose it exists to replace "
        "would satisfy it"
    )


# =========================================================================================
# TRACE-DOD-009 — every status M5 reaches is catalogued, and every transition it implements
# is one document 06 draws. "A state machine that accepts a transition nothing implements is
# a state machine that lies", and the reverse: one that implements a transition nothing
# documents is a state machine nobody agreed to.
#
# `test_review_transitions.py` already compares the review transitions and §29.1 against
# document 06. What this adds is the third authority — the **approved status catalogue** —
# the refusal set by equality, and the transitions that are not reviews.
# =========================================================================================

STATUS_CATALOGUE = REPOSITORY_ROOT / "docs" / "governance" / "status_catalog.yaml"

# `  payment_request:` and everything under it, to the next aggregate at the same indent.
_AGGREGATE = re.compile(r"^  payment_request:$(.*?)(?=^  [a-z_]+:$)", re.M | re.S)
_CANONICAL = re.compile(r"canonical:\s*([a-z_]+)")

# The catalogued statuses M5 deliberately does not reach, each owned by a later milestone.
# **Equality**, not a subset: §2.6 of the plan says M5 refuses the rest, so a status that
# quietly becomes reachable must fail here rather than pass as "still a subset".
M5_REFUSES: dict[str, str] = {
    "batched": "M6 allocates a request to a batch version",
    "sent_to_bank": "M7 marks an export sent",
    "partially_paid": "M8 reconciles bank results",
    "paid": "M8",
    "failed": "M8",
    "retry_required": "M8",
    "result_ready_for_trader": "M9 publishes results",
    "result_published": "M9",
    "trader_acknowledged": "M9",
    "trader_disputed": "M9",
    "closed": "M9 closes a request administratively or operationally",
}


@pytest.fixture(scope="module")
def catalogued_statuses() -> frozenset[str]:
    """The approved canonical statuses for `payment_request`.

    Read from the aggregate's own section, not the whole file: document 06 defines seventeen
    request statuses and the catalogue defines states for a dozen aggregates, several of which
    share names — `cancelled` appears under six. A whole-file parse would compare M5's reach
    against the union of every aggregate's vocabulary and pass on anything.
    """

    text = STATUS_CATALOGUE.read_text(encoding="utf-8")
    assert "catalog_status: approved_phase_1a" in text, (
        "the status catalogue is no longer marked approved, so it is not the authority this "
        "gate treats it as"
    )

    section = _AGGREGATE.search(text)
    assert section is not None, (
        "no `payment_request:` aggregate was found in the status catalogue. A missing entry "
        "must fail here rather than read as 'nothing to check' — which is the live shape of "
        "the DOC-CONFLICT-024 and -048 problem, where value sets were never approved."
    )
    return frozenset(_CANONICAL.findall(section.group(1)))


def test_the_status_catalogue_parse_is_real(catalogued_statuses: frozenset[str]) -> None:
    """Guard the guard. Every set operation below is vacuous against an empty parse."""

    assert len(catalogued_statuses) >= 15, sorted(catalogued_statuses)
    assert {"draft", "needs_trader_correction", "eligible_for_batching", "cancelled"} <= (
        catalogued_statuses
    ), sorted(catalogued_statuses)


def test_every_status_m5_reaches_is_catalogued(catalogued_statuses: frozenset[str]) -> None:
    """`TRACE-DOD-009`, the first half. Imported from the code, never restated here."""

    from app.db.models.payment_request import M5_REACHABLE_STATUSES

    reachable = frozenset(M5_REACHABLE_STATUSES)
    assert reachable, "M5_REACHABLE_STATUSES is empty, so this gate compares nothing"
    assert reachable <= catalogued_statuses, sorted(reachable - catalogued_statuses)


def test_the_statuses_m5_refuses_are_exactly_the_recorded_ones(
    catalogued_statuses: frozenset[str],
) -> None:
    """Equality, because "still a subset" is how a status becomes reachable unnoticed.

    §2.6 of the plan says M5 implements the transitions up to `eligible_for_batching` and
    `cancelled` and refuses the rest. If a later slice made `batched` reachable, the subset
    assertion above would keep passing and nothing would ask whether M6's work had arrived
    early. This is that question, asked as an equality.
    """

    from app.db.models.payment_request import M5_REACHABLE_STATUSES

    refused = catalogued_statuses - frozenset(M5_REACHABLE_STATUSES)

    assert refused == set(M5_REFUSES), (
        "the set of statuses M5 does not reach changed. Each needs a recorded owner.\n"
        f"unrecorded: {sorted(refused - set(M5_REFUSES))}\n"
        f"recorded but now reachable: {sorted(set(M5_REFUSES) - refused)}"
    )


def _implemented_forward_arrows() -> set[tuple[str, str]]:
    """Every `(from, to)` M5 implements, except cancellation.

    Cancellation is excluded and that is not an oversight: document 06's §13.2 diagram
    declares `cancelled` and **draws no arrow into it**, so comparing cancellation against the
    diagram would prove that cancelling is never permitted. §29.1 is its authority instead,
    and `test_review_transitions.py` already compares the code's `CANCELLABLE` table against
    that section row by row, including the actor and reason columns.
    """

    from app.commands.payment_request import CORRECTABLE, REVIEW_TRANSITIONS, SUBMITTED

    arrows = {
        (origin, transition.destination)
        for transition in REVIEW_TRANSITIONS
        for origin in transition.origins
    }
    arrows |= {(origin, SUBMITTED) for origin in CORRECTABLE}
    return arrows


def test_every_transition_m5_implements_is_one_document_06_draws() -> None:
    """`TRACE-DOD-009`, the second half — the direction the plan's sentence names.

    A transition the code accepts and the document does not draw is a state machine nobody
    agreed to, and it is the more dangerous direction: the documented one is reviewed.
    """

    from test_review_transitions import documented_origins

    documented = {
        (origin, destination)
        for destination, origins in documented_origins().items()
        for origin in origins
    }
    assert len(documented) >= 10, "the document 06 parse found almost no arrows"

    invented = sorted(_implemented_forward_arrows() - documented)
    assert invented == [], (
        "these transitions are implemented and document 06 draws none of them:\n"
        + "\n".join(f"{origin} -> {destination}" for origin, destination in invented)
    )


def test_every_documented_transition_between_reachable_states_is_implemented() -> None:
    """And the reverse: a drawn arrow nothing implements is the "state machine that lies".

    Restricted to arrows whose endpoints M5 both reaches — the rest belong to M6 onward and
    are absent on purpose, which `test_the_statuses_m5_refuses_are_exactly_the_recorded_ones`
    is what keeps honest.
    """

    from app.db.models.payment_request import M5_REACHABLE_STATUSES
    from test_review_transitions import documented_origins

    reachable = frozenset(M5_REACHABLE_STATUSES)
    in_scope = {
        (origin, destination)
        for destination, origins in documented_origins().items()
        for origin in origins
        if origin in reachable and destination in reachable
    }
    assert in_scope, "no documented arrow lies between two statuses M5 reaches"

    missing = sorted(in_scope - _implemented_forward_arrows())
    assert missing == [], (
        "document 06 draws these arrows between statuses M5 reaches, and nothing implements "
        "them:\n" + "\n".join(f"{origin} -> {destination}" for origin, destination in missing)
    )


def test_nothing_moves_a_request_forward_out_of_eligible_for_batching() -> None:
    """Where M5 stops, asserted rather than commented.

    `eligible_for_batching` is the milestone's terminal state. Cancellation is the one thing
    that may still leave it — §29.1 permits it while no allocation is active, and M5 has no
    allocations — so this is about *forward* movement: no review transition and no submission
    may take a request onward from there. M6 is what adds `batched`.
    """

    from app.commands.payment_request import ELIGIBLE

    onward = sorted(
        destination
        for origin, destination in _implemented_forward_arrows()
        if origin == ELIGIBLE
    )
    assert onward == [], f"M5 moves an eligible request onward to {onward}"


# =========================================================================================
# TRACE-M5-001 — nothing is owed for M5. The gate that reads the ledger, including its own
# entry, which is why its last edit is the one that removes it.
# =========================================================================================


def test_nothing_is_owed_for_m5() -> None:
    """`TRACE-M5-001`. Every obligation the M5 plan states has left `PENDING`.

    Through `obligations_stated_by` and never a prefix filter. That helper exists because M4's
    gate decided milestone ownership by prefix — `TRACE-` among them — and promptly reported
    M5's `TRACE-DOD-007` as an outstanding M4 obligation. A filter like
    `[k for k in PENDING if k.startswith("TRACE-DOD")]` would reintroduce exactly that defect
    while looking like a simplification.

    This test fails on its own `PENDING` entry until slice 9 removes it as the last edit of
    the milestone. That is the gate working, not a bootstrap problem.
    """

    from test_traceability import PENDING, obligations_stated_by

    plan = REPOSITORY_ROOT / "docs" / "handoff" / "M5_IMPLEMENTATION_PLAN.md"
    assert plan.exists(), f"{plan} is missing, so this gate would compare against nothing"

    stated = obligations_stated_by(plan)

    # Guard the guard, three ways. A helper that returned an empty set would make the
    # intersection below trivially empty — the shape that passes forever.
    assert len(stated) >= 43, f"only {len(stated)} obligations were parsed from the M5 plan"
    assert {
        "TRACE-DOD-007",
        "TRACE-DOD-008",
        "TRACE-DOD-009",
        "TRACE-M5-001",
    } <= stated, sorted(stated)

    outstanding = sorted(stated & PENDING.keys())
    assert outstanding == [], (
        "the M5 plan states these obligations and they are still recorded as pending:\n"
        + "\n".join(outstanding)
    )
