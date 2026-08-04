"""CON-NOIO-001: no file or network I/O inside an open write transaction.

A transaction held across a storage put or an outbound call holds its locks for
the duration of that call. A slow object store then becomes a database
availability problem, and a hung one becomes an outage — every command that
touches the same rows queues behind a request that is waiting on somebody else's
network.

The damage is architectural rather than local. Once one command does it, the
pattern is copied, and by then the fix is every command rather than one.

So this is checked structurally, by parsing rather than by review. The rule: no
call to storage, HTTP, subprocess or `sleep` may appear lexically inside a
`with ... unit_of_work` block. File generation and notification delivery belong
after the commit — the after-commit hook registry exists for exactly that, and it
runs on a separate session precisely so it cannot extend the business
transaction.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPOSITORY_ROOT / "services" / "backend" / "app"

# Attribute and function names that reach outside the process. Matched on the
# call's own name, so `storage.put(...)`, `client.post(...)` and `httpx.get(...)`
# are all caught without needing to resolve what the receiver is.
IO_CALL_NAMES = frozenset(
    {
        "put", "put_object", "upload", "upload_file", "write_bytes", "write_text",
        "save", "store",
        "get", "post", "put_request", "patch", "delete", "request", "send",
        "urlopen", "fetch",
        "run", "check_output", "check_call", "Popen",
        "sleep",
    }
)

# Names that look like I/O and are not. `session.get` is an ORM primary-key
# lookup; `dict.get` and `os.environ.get` are ubiquitous. Matching on the
# receiver keeps the rule from becoming noise everyone learns to ignore.
SAFE_RECEIVERS = frozenset(
    {"session", "self", "os", "environ", "values", "config", "settings", "headers",
     "payload", "metadata", "record", "row", "data", "outcome", "stored", "existing"}
)

UOW_MARKERS = ("unit_of_work", "uow_factory", "uow")


def _is_uow_context(node: ast.With) -> bool:
    """Does this `with` open a Unit of Work?

    Matched on the expression source rather than on a resolved type, because the
    check must work without importing the module under test.
    """

    for item in node.items:
        text = ast.unparse(item.context_expr).lower()
        if any(marker in text for marker in UOW_MARKERS):
            return True
    return False


def _receiver_of(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
        return call.func.value.id
    return None


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def io_calls_inside_transactions(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.With) or not _is_uow_context(node):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            name = _called_name(inner)
            if name not in IO_CALL_NAMES:
                continue
            if _receiver_of(inner) in SAFE_RECEIVERS:
                continue
            # Relative where it can be, absolute otherwise: the planted-violation
            # tests below scan a temporary file that has no package root above it.
            try:
                location = str(path.relative_to(APP_ROOT))
            except ValueError:
                location = path.name
            offenders.append(f"{location}:{inner.lineno}: {ast.unparse(inner.func)}()")
    return offenders


def test_no_module_performs_io_inside_an_open_transaction() -> None:
    offenders: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        offenders.extend(io_calls_inside_transactions(path))

    assert offenders == [], (
        "these calls happen while a write transaction is open, so their latency is "
        "lock-hold time and their failure is a database outage:\n"
        + "\n".join(offenders)
        + "\n\nMove the work after the commit — SqlAlchemyUnitOfWork.after_commit "
        "runs hooks on a separate session for exactly this reason."
    )


def test_the_scanner_finds_a_planted_violation(tmp_path: Path) -> None:
    """Guard the guard.

    A scanner that matches nothing passes over every file in the package and
    reports success, which is indistinguishable from a clean result.
    """

    planted = tmp_path / "offender.py"
    planted.write_text(
        "def command(uow_factory, storage):\n"
        "    with uow_factory() as uow:\n"
        "        uow.session.add(object())\n"
        "        storage.put('key', b'bytes')\n"
        "        uow.commit()\n",
        encoding="utf-8",
    )

    found = io_calls_inside_transactions(planted)

    assert len(found) == 1
    assert "storage.put" in found[0]


def test_the_scanner_does_not_flag_work_after_the_transaction(tmp_path: Path) -> None:
    """The correct shape must not be reported, or the rule becomes noise."""

    correct = tmp_path / "clean.py"
    correct.write_text(
        "def command(uow_factory, storage):\n"
        "    with uow_factory() as uow:\n"
        "        uow.session.add(object())\n"
        "        uow.commit()\n"
        "    storage.put('key', b'bytes')\n",
        encoding="utf-8",
    )

    assert io_calls_inside_transactions(correct) == []


@pytest.mark.parametrize("safe", ["session.get(Model, key)", "values.get('name')"])
def test_ordinary_lookups_are_not_mistaken_for_io(tmp_path: Path, safe: str) -> None:
    """`session.get` is a primary-key lookup and `dict.get` is everywhere.

    Flagging them would produce a rule people learn to ignore, which is worse
    than no rule.
    """

    module = tmp_path / "lookup.py"
    module.write_text(
        "def command(uow_factory, session, values):\n"
        "    with uow_factory() as uow:\n"
        f"        result = {safe}\n"
        "        uow.commit()\n"
        "        return result\n",
        encoding="utf-8",
    )

    assert io_calls_inside_transactions(module) == []
