"""Finalization's locking, its recomputation, and the identity it records — asserted on the code.

M6 slice 3. Three claims that no behavioural test can distinguish from their opposites, so each
is asserted on the module's AST. The pattern is `tests/backend/test_batch_command_shape.py`'s,
and the justification is the same: some properties are about what the code *is*.

**`CON-FINAL-001`: the lock scopes, in the order the module defines them.** Two commands that
each lock their own rows in an obviously-right order deadlock when their sets overlap.
`app/db/locking.py` exists to make that impossible, and its docstring says the rule "lands in M2
rather than when the second command is written" for exactly that reason.

It also had **no caller**. Two milestones after M2 built it for "M5 through M9", `lock_rows` —
the function that issues `SELECT … FOR UPDATE` — was called by nothing in the application and
covered by no test; `test_concurrency_primitives.py` exercises `ordered`, `advisory_key`,
`LockScope` and `LockTarget` as pure functions and never the function that takes a lock. That is
the seventh mechanism-with-no-caller this project has found. `finalize_version` is its first
caller, and this file is what stops the next command from hand-rolling `with_for_update()`
instead.

**`SEC-FINAL-001`: the finalizer comes from the session.** A caller-supplied finalizer would let
one accountant record another as having done the work — the separation rule defeated by its own
evidence. A behavioural test cannot see the difference when the two happen to be the same
person, which they are in every fixture.

**The recomputation must not share a code path with the original computation.** A hash recomputed
by calling the same function that produced it cannot disagree, and a check that cannot fail is
not a check.

Covers: CON-FINAL-001, SEC-FINAL-001.
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


def _calls(function: ast.FunctionDef, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]


def test_finalization_takes_its_locks_through_the_module_that_owns_the_ordering() -> None:
    """`CON-FINAL-001`. `lock_rows`, not a hand-rolled `with_for_update()`.

    The distinction is the whole value of `app/db/locking.py`: `lock_rows` sorts targets by
    `(scope.order, table, primary key)` before locking, so a caller cannot get the order wrong by
    being locally reasonable. A direct `with_for_update()` locks in whatever order the business
    logic produced, which is how the M6/M9 deadlock pair the module's docstring names comes back.
    """

    function = _function("finalize_version")

    assert _calls(function, "lock_rows"), (
        "finalize_version does not call lock_rows. `command_catalog.yaml:139` says "
        "`if_match_batch_and_lock_current_version`, and `app/db/locking.py` is the module that "
        "owns the global lock ordering — this command is its first caller."
    )
    assert not _calls(function, "with_for_update"), (
        "finalize_version takes a lock directly with with_for_update(), bypassing the global "
        "ordering rule. Two commands locking overlapping rows in locally-sensible orders "
        "deadlock, which is the failure app/db/locking.py exists to prevent."
    )


def test_the_lock_targets_use_the_scope_the_enum_reserved_for_finalization() -> None:
    """`BATCH_VERSION_FINALISE`, and both rows the command decides about.

    The scope numbers are the ordering, and they ascend with the flow of value through the
    system. Using a different scope here — `BATCH_VERSION_APPROVAL`, say — would place this
    command's locks after a command that must run later, which is a deadlock the enum was
    designed to make visible rather than possible.
    """

    function = _function("finalize_version")
    scopes = {
        node.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "LockScope"
    }
    assert scopes == {"BATCH_VERSION_FINALISE"}, (
        f"finalize_version uses lock scopes {sorted(scopes)}; it should use exactly "
        "BATCH_VERSION_FINALISE, which app/db/locking.py reserved for it"
    )

    targets = {
        argument.id
        for call in _calls(function, "of")
        for argument in call.args
        if isinstance(argument, ast.Name)
    }
    assert {"PaymentBatch", "PaymentBatchVersion"} <= targets, (
        f"finalize_version locks {sorted(targets)}; it decides about both the container and the "
        "version, so both rows have to be locked before either is read"
    )


def test_the_locks_are_taken_before_anything_is_read() -> None:
    """Read-then-lock leaves a window in which what was read stops being true.

    Asserted by line position: every `session.get` and `select` in the function body has to come
    after the `lock_rows` call. A guard evaluated against a row that changed between the read and
    the lock is a guard that passed for a state that no longer exists.
    """

    function = _function("finalize_version")
    lock_line = min(call.lineno for call in _calls(function, "lock_rows"))

    reads = [
        call.lineno
        for name in ("get", "select", "execute", "scalar")
        for call in _calls(function, name)
    ]
    # The idempotency claim runs before the lock on purpose: it is the thing that decides whether
    # this call executes at all, and it holds its own unique index. It is excluded by name rather
    # than by line, so a future read inserted above the lock still fails.
    claim_lines = {call.lineno for call in _calls(function, "claim")}
    early = sorted(line for line in reads if line < lock_line and line not in claim_lines)

    assert early == [], (
        f"finalize_version reads at line(s) {early}, before it locks at line {lock_line}. "
        "Whatever those reads decide can stop being true before the lock is taken."
    )


def test_the_finalizer_is_the_session_actor_and_never_the_payload() -> None:
    """`SEC-FINAL-001`.

    Asserted on the assignment: `finalized_by_admin_user_id` is set from `actor.actor_id`, and
    the command dataclass has no field a caller could put an identity in. Both halves matter —
    the first is what the code does today, and the second is what stops a field being added and
    wired up later without anybody noticing that the separation rule now trusts its subject.
    """

    function = _function("finalize_version")

    assignments = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Attribute)
            and target.attr == "finalized_by_admin_user_id"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1, (
        f"expected exactly one assignment to finalized_by_admin_user_id, found "
        f"{len(assignments)}"
    )
    assigned = ast.unparse(assignments[0].value)
    assert assigned == "actor.actor_id", (
        f"the finalizer is recorded from {assigned!r}. It must come from the session actor: a "
        "caller-supplied finalizer would let one accountant record another as having done the "
        "work, which is `FINANCIAL_INTEGRITY_BASELINE.md` §5 defeated by its own evidence."
    )

    command = next(
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.ClassDef) and node.name == "FinalizeVersion"
    )
    fields = {
        target.target.id
        for target in command.body
        if isinstance(target, ast.AnnAssign) and isinstance(target.target, ast.Name)
    }
    identity_fields = {
        field for field in fields if "admin_user" in field or "finaliz" in field
    }
    assert identity_fields == set(), (
        f"FinalizeVersion carries {sorted(identity_fields)}, so a caller can name the finalizer. "
        "The command must take the target and the note and nothing about who is acting."
    )


def test_the_recomputed_hash_does_not_share_a_code_path_with_the_original() -> None:
    """A check that cannot fail is not a check.

    `_verify_internally_consistent` recomputes the content hash through
    `_content_hash_from_stored`, which reads persisted rows. If it called `_content_hash` — the
    function `create_batch` used — the two would agree by construction and `SVC-FINAL-001` would
    assert nothing at all.

    What they *do* share is `unversioned_digest`, the canonical serialiser, which is the part
    that must agree. Asserted so the sharing stays on the right side of the line.
    """

    verifier = _function("_verify_internally_consistent")
    assert not _calls(verifier, "_content_hash"), (
        "_verify_internally_consistent calls _content_hash, the function that produced the "
        "stored value. The recomputation would then agree by construction and could never "
        "detect an edited row."
    )
    assert _calls(verifier, "_content_hash_from_stored"), (
        "_verify_internally_consistent does not recompute the content hash at all, so a version "
        "whose rows changed after creation would finalize and bind an approval to content "
        "nobody reviewed"
    )

    recomputer = _function("_content_hash_from_stored")
    assert _calls(recomputer, "unversioned_digest"), (
        "_content_hash_from_stored does not use the shared canonical serialiser, so the two "
        "digests could differ for a reason other than the content differing"
    )
