"""The storage machinery must be called by something that is not a test.

Covers: TRACE-CALLER-001.

M3 shipped five mechanisms that were complete, tested, and imported nowhere: the security
stamp, the step-up context store, `loadSession` on both auth adapters, `stateForError`,
and `logout`. Every one had unit tests that called it directly, which is exactly why the
suite never noticed.

M4 began in the same state, at the scale of a whole milestone. `app/storage/` shipped in
M2 with a backend protocol, a local adapter, an opaque key builder and six reconciliation
checks, and a search for all of them returned six files: the four that define them, the
runtime container that constructs the backend, and the health probe that pings it. The
platform checked at startup that it could reach a storage backend it never wrote to.

So this is a rule over the import graph rather than a grep for a name. It asks the
question no other test in the suite asks — *does anything call this* — and it is
deliberately not satisfied by the readiness probe, because a probe proves the dependency
is reachable and nothing about whether the product uses it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / "services" / "backend" / "app"

# The two modules that legitimately touch the backend for reasons other than storing a
# file. Asserted as an exact set below rather than merely excluded, so that it cannot grow
# quietly: a third module appearing here is a boundary change and should be argued for.
INFRASTRUCTURE = {
    "core/runtime.py",  # constructs the backend into the runtime container
    "observability/health.py",  # readiness probe
}


def _modules() -> list[Path]:
    return sorted(path for path in APP.rglob("*.py") if "__pycache__" not in path.parts)


def _relative(path: Path) -> str:
    return path.relative_to(APP).as_posix()


def _names_used(path: Path) -> set[str]:
    """Every identifier the module *uses*, from the parsed source.

    An AST rather than a substring search: `generate_storage_key` appearing inside a
    docstring is documentation, and counting it would let a comment satisfy this gate.
    That is the citation-as-coverage hazard this repository has already been bitten by.

    **Imports are deliberately not counted.** The first version of this collected
    `ImportFrom` aliases too, and the negative control caught it: replacing the call to
    `generate_storage_key` with a hard-coded string left the import at the top of the
    module, and the gate still reported a caller. An unused import is the exact shape of
    "complete machinery nothing calls" — it is what the mechanism looks like on the way
    to being abandoned — so counting it would have made this gate report green against
    the defect it was written for.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def _callers(symbol: str, *, exclude_prefix: str) -> set[str]:
    return {
        _relative(path)
        for path in _modules()
        if not _relative(path).startswith(exclude_prefix) and symbol in _names_used(path)
    }


def test_the_module_scan_finds_the_application() -> None:
    """Guard the guard: an empty scan makes every assertion below vacuous."""

    modules = _modules()
    assert len(modules) > 50, f"only {len(modules)} modules found under {APP}"


def test_an_import_alone_does_not_count_as_a_caller(tmp_path: Path) -> None:
    """Guard the guard, and the one that matters most here.

    A module that imports a symbol and never uses it is exactly what an abandoned
    mechanism looks like. If the scan counted imports, this gate would report a caller
    for machinery nothing invokes — which is the failure it exists to catch, committed
    against the gate itself. Found by the negative control, not by review.
    """

    importer = tmp_path / "importer.py"
    importer.write_text(
        "from app.storage.keys import generate_storage_key\n"
        "\n"
        "def build() -> str:\n"
        '    return "hard/coded/key"\n',
        encoding="utf-8",
    )
    assert "generate_storage_key" not in _names_used(importer)

    caller = tmp_path / "caller.py"
    caller.write_text(
        "from app.storage.keys import generate_storage_key\n"
        "\n"
        "def build(purpose, moment):\n"
        "    return generate_storage_key(category=purpose, moment=moment)\n",
        encoding="utf-8",
    )
    assert "generate_storage_key" in _names_used(caller)


@pytest.mark.parametrize("symbol", ["generate_storage_key", "write"])
def test_the_storage_write_path_has_a_production_caller(symbol: str) -> None:
    """TRACE-CALLER-001.

    `generate_storage_key` had no caller at all before this slice, and `write` on the
    backend had none either — the readiness probe calls `check_available`, not `write`.
    """

    callers = _callers(symbol, exclude_prefix="storage/")
    outside_infrastructure = callers - INFRASTRUCTURE

    assert outside_infrastructure, (
        f"nothing outside app/storage/ calls {symbol!r}. The mechanism exists and the "
        "product does not use it, which is the defect that recurred five times in M3 — "
        "a readiness probe reaching a backend is not the product storing a file."
    )


def test_the_infrastructure_allowlist_is_exactly_what_is_recorded() -> None:
    """The allowlist is an exact set, not a floor.

    Excluding `core/runtime.py` and `observability/health.py` is what makes the test above
    meaningful. If a third module were added to the allowlist to make a failure go away,
    the gate would weaken silently — so the recorded set is asserted, and changing it is a
    visible edit with a reason.
    """

    recorded = {"core/runtime.py", "observability/health.py"}
    assert recorded == INFRASTRUCTURE

    for module in INFRASTRUCTURE:
        assert (APP / module).exists(), f"the allowlist names {module}, which does not exist"


def test_the_upload_command_is_reachable_from_a_route() -> None:
    """The other half of the same question, one level up.

    A command with a production caller that is another command is still a mechanism
    nothing reaches. This asserts the chain ends at a router module — the shape M3's
    slice 8E got wrong by shipping ten routes and no screen, and that the trader app got
    wrong by shipping `logout` with no caller.
    """

    route_modules = [path for path in _modules() if _relative(path).startswith("api/v1/")]
    assert route_modules, "no route modules found; the path convention changed"

    importers = {
        _relative(path)
        for path in route_modules
        if "upload" in _names_used(path) or "execute" in _names_used(path)
    }
    assert "api/v1/files.py" in importers, (
        "no route module references the upload command; the command exists and nothing "
        "serves it"
    )
