"""Two claims `create_batch`'s docstring makes that no behavioural test can see.

Written because two negative controls came back **NOT CAUGHT**, and following each was worth
more than the eighteen that fired.

**The attempt passes through `created`.** `06_Workflows_and_State_Machines.md:676-677` draws
`[*] --> created` and then `created --> included_in_batch_version`. Inserting the final status
directly is *observationally identical*: the transaction commits with the same row either way,
so no integration test can distinguish them. The difference is whether document 06's initial
state is reachable by any code path at all — and a state nothing can produce is the mirror image
of a transition nothing implements. This milestone has now found both shapes, so the claim gets
an assertion rather than a comment.

**Nothing here checks for an existing allocation before inserting one.**
`FINANCIAL_INTEGRITY_BASELINE.md:39-40` says a service-layer check is insufficient, and the
reason is not that it is redundant — it is that it is *wrong*: two concurrent transactions both
pass a `SELECT`, both proceed, and one double payment leaves the building. A future maintainer
looking at an `IntegrityError` in a log will be tempted to "fix" it with a pre-check, and the
integration suite would stay green while the race reopened.

Both are asserted on the module source, for the reason `tests/backend/test_splitting.py` gives
about the engine's signature: some properties are about what the code *is*, not what it returns,
and a test that can only observe returns cannot see them. No database, so neither can be skipped.

Covers: SVC-BATCH-001, DB-ALLOC-001.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.commands import payment_batch

SOURCE = Path(inspect.getfile(payment_batch)).read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not in {payment_batch.__name__}")


def test_the_attempt_is_inserted_at_created_and_moved_afterwards() -> None:
    """The insert carries `ATTEMPT_CREATED`; the transition is a separate assignment.

    Two halves, and both are needed. If only the constant appeared, the attempt could be
    inserted at `created` and left there — an attempt in a batch that says it is not in one. If
    only the assignment appeared, the insert could already carry the final value and the
    assignment would be a no-op.

    **Asserted over the module, not over `create_batch`.** Slice 4 extracted `_attempts_for` and
    `_insert_items_and_allocate` so the replacement command shares one splitting path rather than
    copying it, and this gate failed — correctly about the property, wrongly about where to look.
    A gate that has to be edited whenever a helper is extracted is a gate somebody eventually
    edits by deleting.
    """

    function = TREE

    constructed_at_created = [
        keyword
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PaymentAttempt"
        for keyword in node.keywords
        if keyword.arg == "status"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "ATTEMPT_CREATED"
    ]
    assert constructed_at_created, (
        "the attempt is not constructed with ATTEMPT_CREATED. Document 06's attempt machine "
        "starts at `created` (`:676`); inserting the final status directly leaves that state "
        "unreachable by any code path, and the arrow `created --> included_in_batch_version` "
        "unimplemented. No integration test can see this — the committed row is identical."
    )

    moved_afterwards = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ATTEMPT_INCLUDED"
    ]
    assert moved_afterwards, (
        "nothing assigns ATTEMPT_INCLUDED, so an attempt stays at `created` after its item and "
        "allocation exist — a row in a batch whose own status says it is not in one"
    )


def test_a_flush_separates_the_insert_from_the_transition() -> None:
    """The intermediate state has to reach the database, or the sequence is a fiction.

    Without a flush between them, SQLAlchemy coalesces the insert and the update: the INSERT
    carries the final status and the row never holds `created`. That is exactly the state of
    affairs this file exists to distinguish, so the flush is part of the claim rather than an
    implementation detail.

    Also module-scoped since slice 4: the insert is in `_attempts_for`, the flush is in its
    caller and again inside `_insert_items_and_allocate`, and the transition is in that second
    helper. Positions in the file rather than in one function, which is what the property was
    always about — the database has to see the INSERT before the UPDATE, and it does not care
    which function issued either.
    """

    function = TREE

    def line_of(predicate: object) -> int:
        for node in ast.walk(function):
            if predicate(node):  # type: ignore[operator]
                return node.lineno
        raise AssertionError("not found")

    insert_line = line_of(
        lambda node: isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PaymentAttempt"
    )
    transition_line = line_of(
        lambda node: isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Name)
        and node.value.id == "ATTEMPT_INCLUDED"
    )
    flushes = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "flush"
    ]

    assert any(insert_line < flush < transition_line for flush in flushes), (
        f"no flush between the attempt insert (line {insert_line}) and its transition "
        f"(line {transition_line}); flushes are at {flushes}. Without one the INSERT carries "
        "the final status and the row never holds `created`."
    )


def test_nothing_selects_an_existing_allocation_before_inserting_one() -> None:
    """`DB-ALLOC-001`'s other half: the absence of a check is the design.

    A `SELECT` before the insert is not a harmless belt-and-braces. Under READ COMMITTED two
    concurrent transactions both see no row, both decide to proceed, and both insert — so the
    pre-check converts a reliable database refusal into a race that succeeds. The baseline says
    "service-layer checks alone are insufficient"; this asserts that none was added *beside* the
    constraint either, because a maintainer reading an `IntegrityError` in a log will reach for
    exactly that.
    """

    function = _function("create_batch")

    offenders = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "select"
        and any(
            isinstance(argument, ast.Attribute | ast.Name)
            and "Allocation" in ast.unparse(argument)
            for argument in node.args
        )
    ]
    assert offenders == [], (
        f"create_batch queries PaymentAttemptAllocation at line(s) {offenders}. Whatever that "
        "query decides, two concurrent transactions decide it the same way and both proceed — "
        "the partial unique index is the only thing that can refuse the second."
    )
