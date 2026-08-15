"""Test module basenames must be unique across the suite.

pytest derives a module name from a file's basename when its directory is not a package,
and `tests/backend` and `tests/integration` are both plain directories. Two files sharing
a basename therefore collide at import and pytest refuses to collect either — not with a
failure inside a test, but with a collection error that stops the entire run.

The reason this needs a gate rather than a convention is what it took to find: running
`pytest tests/backend` and `pytest tests/integration` separately both pass, because
neither run sees the other's file. The collision only appears when both are collected
together, which is what CI does. So the local signal was green, twice, on a suite that
could not start.

91 test files had unique basenames before M4 slice 3 added the 92nd, which means the
convention was real and unwritten. This writes it down.
"""

from __future__ import annotations

import collections
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
SUITES = ("backend", "integration")


def _modules() -> list[Path]:
    found: list[Path] = []
    for suite in SUITES:
        found.extend(sorted((TESTS / suite).glob("test_*.py")))
    return found


def test_the_scan_finds_both_suites() -> None:
    """Guard the guard: an empty or single-suite scan cannot find a collision."""

    modules = _modules()
    assert len(modules) > 50, f"only {len(modules)} test modules found under {TESTS}"

    for suite in SUITES:
        assert any(path.parent.name == suite for path in modules), (
            f"no test modules found in tests/{suite}; the layout changed and this gate "
            "is no longer looking where the files are"
        )


def test_no_two_test_modules_share_a_basename() -> None:
    """The rule itself.

    Reported with both paths, because the fix is to rename one of them and the useful
    question is which — the name should say what the file covers, and a collision usually
    means two files claim the same subject at different levels.
    """

    locations: dict[str, list[str]] = collections.defaultdict(list)
    for path in _modules():
        locations[path.name].append(str(path.relative_to(TESTS)))

    collisions = {name: paths for name, paths in locations.items() if len(paths) > 1}

    assert collisions == {}, (
        "these test modules share a basename and pytest cannot collect them together:\n"
        + "\n".join(
            f"  {name}: {', '.join(paths)}" for name, paths in sorted(collisions.items())
        )
        + "\nRename one so its name says what it covers. Running one directory at a time "
        "hides this; CI collects both."
    )


def test_neither_suite_is_a_package() -> None:
    """The assumption the rule rests on.

    If either directory gained an `__init__.py`, module names would be
    `tests.backend.test_x` and the collision would not exist — and this gate would be
    enforcing a restriction nothing needs. Recorded so the rule can be retired
    deliberately rather than left in place after its reason has gone.
    """

    for suite in SUITES:
        assert not (TESTS / suite / "__init__.py").exists(), (
            f"tests/{suite} is now a package, so basenames no longer have to be unique. "
            "Retire this gate rather than leaving it to enforce a rule nothing needs."
        )
