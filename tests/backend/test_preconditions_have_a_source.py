"""Every command that demands `If-Match` has a read that issues one.

M11 Screens slice 5, and this file exists because the same defect appeared twice one milestone
apart:

- **slice 4**: the four payment-attempt commands required `If-Match` on the attempt, and no
  operation in the contract returned an attempt's `record_version` as an `ETag`.
  `AttemptResult` carried the number but only ever as a *response to a confirmation* — the version
  arrived after acting and never before it.
- **slice 5**: the four gold-sale-order commands required `If-Match` on the order, and
  `GET /gold-sale-orders/{order_id}` returned `record_version` in the body with no header.

Both times the screen's only option was to build `"rv-${record_version}"` itself, and both times
that is exactly what `apps/admin-web/test/preconditions-come-from-the-server.test.ts` was written
to forbid: **a computed precondition is present, well-formed and meaningless.** It passes the
server's parser, satisfies any check that the header exists, and compares the wrong state — so two
people acting on one row both succeed and the second silently overwrites the first.

Twice is a pattern. This asks the question once, over the whole contract, so the third time is
caught before a screen is written against it rather than while writing one.

**Structural on purpose.** Whether a *particular* stale version is refused is a behavioural claim
and belongs to the integration suite, where several such tests already live. What cannot be asked
there is the negative shape this file is about — that somewhere in the contract there exists a read
a client can get the precondition from. A missing read fails no request; it just leaves callers
with nothing to echo.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPOSITORY_ROOT / "services" / "backend" / "openapi" / "v1.json"
ROUTERS = REPOSITORY_ROOT / "services" / "backend" / "app" / "api"

# `POST /api/v1/payment-attempts/{attempt_id}/confirm-paid` needs a read of
# `/api/v1/payment-attempts/{attempt_id}`. The precondition is against the aggregate the command
# hangs off, so the read is the command path with its trailing action segments removed.
_ACTION_SUFFIX = re.compile(r"(/[a-z0-9-]+)+$")

# Commands whose `If-Match` is not about the aggregate their path names, each naming **the read
# that does issue it** and why.
#
# **The read is part of the entry, not the prose, and the sabotage run is why.** The first version
# held a sentence only, and `scripts/control-gap-becomes-exemption.py` showed what that costs: a
# recorded gap can be promoted to an exemption with one plausible line, no code change, and nothing
# to compare it against. An exemption asserts that a particular read supplies the precondition —
# so it says which, and `test_every_exemption_names_a_read_that_exists` checks it.
EXEMPT: dict[tuple[str, str], tuple[str, str]] = {
    ("POST", "/api/v1/me/trader/payment-requests/{request_id}/acknowledge-result"): (
        "/{payment_request_id}",
        "the version is the *request's*, and `GET /api/v1/payment-requests/{payment_request_id}` "
        "issues it — the trader reaches the same aggregate by a different path"
    ),
    ("POST", "/api/v1/me/trader/payment-requests/{request_id}/dispute-result"): (
        "/{payment_request_id}",
        "same as acknowledge-result: the precondition is the request's version"
    ),
    ("POST", "/api/v1/payment-requests/{request_id}/publications"): (
        "/{payment_request_id}",
        "the version is the request's rather than the publication's — a publication has no prior "
        "version to be stale against, and `getPaymentRequest` issues the ETag"
    ),
    ("POST", "/api/v1/payment-requests/{request_id}/publications/corrections"): (
        "/{payment_request_id}",
        "the request's version again, and no role holds `payment_publication.correct` pending "
        "ADR-SEC-009, so no screen reaches this route at all"
    ),
    ("POST", "/api/v1/gold-sale-orders/{order_id}/dispatches/{dispatch_id}/acknowledge"): (
        "/{order_id}",
        "the version is the *order's*, not the dispatch's: §8.2 moves both rows and the order is "
        "the aggregate. `getGoldSaleOrder` issues it as of M11 Screens slice 5"
    ),
    ("PUT", "/api/v1/roles/{role_id}/permissions"): (
        "/{role_id}",
        "the precondition is the *role's* and `getRole` issues it — and it is the one ETag in this "
        "contract that is not a record version at all: `role_permissions.permission_etag(codes)` "
        "hashes the granted set, so two roles with identical permissions share an ETag and a "
        "concurrent edit that lands on the same set is correctly not a conflict. A per-row version "
        "would report one"
    ),
    ("POST", "/api/v1/payment-batches/{batch_id}/versions/{version_id}/finalize"): (
        "/{batch_id}",
        "the version is the *batch's*, which the route's own docstring states: a batch version is "
        "an immutable snapshot and deliberately has no `record_version`, because giving it one "
        "would invite a compare-and-swap against a record nobody may modify. `getBatch` issues the "
        "ETag for the aggregate that can move"
    ),
}

# Commands whose precondition has **no source at all**, with what would supply one.
#
# Separate from `EXEMPT` on purpose, and the distinction is the point of this file. An exemption
# says "the precondition is about a different aggregate, and here is the read that issues it" — a
# design. A gap says "there is nowhere to get this", which is the defect, recorded because it
# cannot be fixed inside the slice that found it.
#
# **A gap here is a promise, not a licence.** Each names the slice that closes it, and closing one
# is a deletion from this dict rather than an edit to it — which is how a recorded gap differs
# from a floor somebody keeps adjusting.
RECORDED_GAPS: dict[tuple[str, str], str] = {
    # M11 Screens slice 6 closed both incoming-payment entries by building the two reads —
    # `GET /incoming-payment-receipts/{receipt_id}` and `GET .../matches/{match_id}` — which is
    # what a closed gap looks like here: a deletion rather than an edit.
    #
    # **Slice 5 got one of them wrong, and reading the route while building the screen is what
    # found it.** The reject entry said "the precondition is the receipt's". It is the *match's*:
    # the route passes `incoming_payment_match_id` and edits the match row. So the gap needed a
    # second read rather than the same one, and a recorded gap stating the wrong aggregate would
    # have been closed by a read that did not satisfy it — the check would have gone green while
    # the screen still had nothing to echo.
    ("POST", "/api/v1/center-profile/rename"): (
        "there is no `GET /center-profile`, and this route is guarded by an **operations token** "
        "rather than a session — `test_m3_definition_of_done.py` classifies it `OPERATIONS`. No "
        "screen calls it and none is planned, so the caller is an operator with a shell rather "
        "than a person with a browser. Recorded rather than fixed: adding a session-guarded read "
        "for an operations-token surface would be a new disclosure decision, which belongs to "
        "whoever needs it. **Note also that it issues a bare `\"{n}\"` ETag rather than "
        "`\"rv-{n}\"`** — the only route in the contract that does."
    ),
}


def commands_requiring_if_match() -> dict[tuple[str, str], str]:
    """Every operation declaring an `If-Match` header, from the published contract."""

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    found: dict[tuple[str, str], str] = {}
    for path, operations in contract["paths"].items():
        for method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            headers = {
                parameter["name"].lower()
                for parameter in operation.get("parameters", [])
                if parameter.get("in") == "header"
            }
            if "if-match" in headers:
                found[(method.upper(), path)] = operation.get("operationId", "")
    return found


def reads_issuing_an_etag() -> set[str]:
    """Every GET path whose handler sets an `ETag` header.

    Read from the source rather than from the contract, because FastAPI does not describe a header
    a handler sets by hand — the contract cannot answer this question and a check written against
    it would find nothing and pass.

    An AST walk rather than a substring search: `response.headers["ETag"] = ...` inside a docstring
    or a comment is prose about the rule, and this project has now tripped three structural checks
    on their own explanations.
    """

    issuing: set[str] = set()
    for source in sorted(ROUTERS.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not _sets_an_etag(node):
                continue
            for path in _get_paths(node):
                issuing.add(path)
    return issuing


def _sets_an_etag(function: ast.FunctionDef) -> bool:
    """`response.headers["ETag"] = ...` anywhere in the body."""

    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and str(target.slice.value).lower() == "etag"
            ):
                return True
    return False


def _get_paths(function: ast.FunctionDef) -> list[str]:
    """The `@router.get("...")` paths this function is registered at, prefixed to `/api/v1`.

    The router prefix is not visible from the decorator, so the path is matched by suffix below
    rather than reconstructed here — which is why this returns the decorator's own literal.
    """

    paths: list[str] = []
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        if not isinstance(target, ast.Attribute) or target.attr != "get":
            continue
        if decorator.args and isinstance(decorator.args[0], ast.Constant):
            paths.append(str(decorator.args[0].value))
    return paths


def aggregate_read_for(method: str, path: str) -> str:
    """The read path a command's precondition should come from.

        POST  /api/v1/payment-attempts/{attempt_id}/confirm-paid
           -> /api/v1/payment-attempts/{attempt_id}

        PATCH /api/v1/me/trader/profile
           -> /api/v1/me/trader/profile

    **`PATCH` and `PUT` edit the thing their path names**, so the read is the path itself. The
    first version of this function trimmed every path back to its last `{parameter}` and reported
    `PATCH /me/trader/profile` as orphaned — a singleton resource has no path parameter to stop at,
    so the trim ran off the end. The gate was right that something was wrong and wrong about what,
    which is worth recording: a resolver that cannot express one shape reports it as a defect in
    the code rather than in itself.
    """

    if method in {"PATCH", "PUT"}:
        return path

    trimmed = path
    while not trimmed.endswith("}") and trimmed.count("/") > 3:
        trimmed = trimmed.rsplit("/", 1)[0]
    return trimmed


def test_the_reader_finds_the_commands_and_the_reads() -> None:
    """Guard the guard, before anything is compared.

    A contract parse that found no `If-Match` operations, or an AST walk that found no ETag
    setters, would make the check below vacuously true — which is precisely the shape of the two
    defects it exists to prevent.
    """

    commands = commands_requiring_if_match()
    issuing = reads_issuing_an_etag()

    assert len(commands) >= 10, (
        f"only {len(commands)} operations declare If-Match; the contract parse is not finding them"
    )
    assert len(issuing) >= 4, (
        f"only {len(issuing)} reads issue an ETag; the AST walk is not finding them"
    )
    # Anchored on the two this file was written about, so a walk that started returning nonsense
    # would not silently satisfy the count above.
    assert any(path.endswith("{attempt_id}") for path in issuing), (
        "the attempt read no longer issues an ETag; slice 4's fix has been undone"
    )
    assert any(path.endswith("{order_id}") for path in issuing), (
        "the gold order read no longer issues an ETag; slice 5's fix has been undone"
    )


def test_every_if_match_command_has_a_read_that_issues_one() -> None:
    """**The property, asked once for the whole contract.**

    For every command demanding `If-Match`, some GET must publish an `ETag` for the aggregate it
    hangs off — otherwise the only way to satisfy the precondition is to compute it, and a computed
    precondition compares a state nobody observed.

    Exemptions are named individually with their reasoning rather than pattern-matched: a command
    whose precondition is a *different* aggregate is a real design, and one whose precondition has
    no source at all is the defect. Only a sentence tells them apart.
    """

    issuing = reads_issuing_an_etag()
    orphaned: dict[str, str] = {}

    for (method, path), operation in sorted(commands_requiring_if_match().items()):
        if (method, path) in EXEMPT or (method, path) in RECORDED_GAPS:
            continue
        expected = aggregate_read_for(method, path)
        # Suffix rather than equality: the decorator's literal omits the router prefix.
        if not any(expected.endswith(declared) for declared in issuing):
            orphaned[f"{method} {path}"] = operation

    assert orphaned == {}, (
        "these commands require `If-Match` and no read issues an ETag for the aggregate they act "
        f"on, so a client can only compute the precondition:\n{json.dumps(orphaned, indent=2)}\n"
        "Add the ETag to the aggregate's read, add an entry to EXEMPT saying which aggregate the "
        "precondition is really about, or add one to RECORDED_GAPS naming the slice that closes "
        "it."
    )


def test_no_recorded_gap_has_quietly_been_closed() -> None:
    """A gap that has been fixed must leave this dict, not sit in it.

    **This is what stops the recorded gaps becoming a place things go to be forgotten.** An entry
    whose read now issues an ETag is excusing nothing, and the next person reading the list would
    believe three surfaces are unreachable when one of them is not.

    The same shape as `test_no_classification_names_a_route_that_is_gone` and
    `test_no_pending_obligation_is_already_covered`: the project's own answer to lists that only
    ever grow.
    """

    issuing = reads_issuing_an_etag()
    closed: list[str] = []

    for method, path in RECORDED_GAPS:
        expected = aggregate_read_for(method, path)
        if any(expected.endswith(declared) for declared in issuing):
            closed.append(f"{method} {path}")

    assert closed == [], (
        f"these are recorded as having no precondition source and now have one: {closed}. Delete "
        "the entry — a closed gap left in the list is a claim that something is broken when it is "
        "not."
    )


def test_every_recorded_gap_says_what_would_close_it() -> None:
    """A gap with no remedy is a complaint. Each entry names the read that is missing.

    Asserted on the text for the same reason the exemptions are: only a sentence distinguishes
    "this needs a read nobody has built yet" from "we could not make it work".
    """

    for key, reason in RECORDED_GAPS.items():
        assert len(reason) > 60, f"{key} is recorded as a gap with no explanation worth reading"
        assert "GET" in reason or "read" in reason, (
            f"{key}'s entry does not say which read is missing"
        )


def test_the_two_kinds_of_entry_are_not_conflated() -> None:
    """No command may be both exempt and a recorded gap.

    They mean opposite things — "the precondition comes from elsewhere" and "the precondition
    comes from nowhere" — and an entry in both would let a real gap hide behind a design.
    """

    overlap = sorted(f"{method} {path}" for method, path in set(EXEMPT) & set(RECORDED_GAPS))
    assert overlap == [], f"these are both exempt and recorded as gaps: {overlap}"


def test_no_exemption_names_a_command_that_is_gone() -> None:
    """A stale exemption silently excuses nothing, forever — and hides the next real gap.

    The same failure `test_the_allowlist_names_only_routes_that_exist` guards for the permission
    allowlist, and for the same reason: an entry nobody can reach is an entry nobody rereads.
    """

    commands = set(commands_requiring_if_match())
    stale = sorted(
        f"{method} {path}"
        for method, path in {**EXEMPT, **RECORDED_GAPS}
        if (method, path) not in commands
    )

    assert stale == [], (
        f"these exemptions name commands that no longer require If-Match: {stale}"
    )


def test_every_exemption_names_a_read_that_exists() -> None:
    """**What makes an exemption a claim rather than a licence**, and the sabotage run is why.

    `scripts/control-gap-becomes-exemption.py` promotes a recorded gap into `EXEMPT` with a
    plausible sentence. Against the first version of this file — where an exemption was prose
    only — **nothing caught it**: a defect became a design with one line, no code change, and
    nothing to compare the sentence against.

    An exemption asserts that some *particular* read supplies the precondition. So it names that
    read, and the read has to issue an ETag. An entry whose read does not exist fails here, which
    is the difference between "the precondition comes from elsewhere" and "we said it does".
    """

    issuing = reads_issuing_an_etag()

    for key, (read_path, reason) in EXEMPT.items():
        assert read_path in issuing, (
            f"{key} is exempt because {read_path!r} supplies its precondition, and no handler "
            f"registered at that path issues an ETag. Reads that do: {sorted(issuing)}"
        )
        assert len(reason) > 40, f"{key} is exempt with no explanation worth reading"
        assert "version" in reason or "aggregate" in reason, (
            f"{key}'s exemption does not say which aggregate its precondition is about"
        )
