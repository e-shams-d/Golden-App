"""The two copies of "which navigation items are ungated" say the same thing.

M11 Screens slice 10, and it exists because **the same divergence happened twice**.

`UI-NAV-001` is asserted in two places by design: `apps/admin-web/test/navigation-permissions.
test.ts` imports the navigation module, and `tests/integration/test_navigation_is_not_a_control.py`
parses it as text — the half that proves the frontend is *not* the control cannot be written in the
frontend.

Both hold an equality over the ungated items. Slice 1 widened it from one to two and updated only
the vitest copy; CI caught it. Slice 10 widened it from two to three and **updated only the vitest
copy again**, with a comment in that file explicitly saying "change one, change both" — which was
read after the fact rather than before.

A pointer is documentation. This is the gate: the two lists are extracted and compared, so the next
divergence fails in seconds on a developer machine rather than after a fifty-minute integration
run.

**Neither list is treated as the source.** They disagree in *either* direction and this fails,
because the question is not which is right but that a rule written twice has drifted.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VITEST = REPOSITORY_ROOT / "apps" / "admin-web" / "test" / "navigation-permissions.test.ts"
INTEGRATION = REPOSITORY_ROOT / "tests" / "integration" / "test_navigation_is_not_a_control.py"

# `expect(ungated.map((item) => item.href)).toEqual(["/", "/password", "/notifications"]);`
_VITEST_EQUALITY = re.compile(
    r"ungated\.map\(\(item\) => item\.href\)\)\.toEqual\(\[([^\]]*)\]\)"
)
# `UNGATED = frozenset({"/", "/password", "/notifications"})`
_PYTHON_SET = re.compile(r"UNGATED = frozenset\(\{([^}]*)\}\)")
_QUOTED = re.compile(r'"([^"]*)"')


def vitest_ungated() -> list[str]:
    found = _VITEST_EQUALITY.search(VITEST.read_text(encoding="utf-8"))
    assert found is not None, (
        f"no ungated equality found in {VITEST.name}; the pattern no longer matches how that "
        "test writes it, and this comparison would be about nothing"
    )
    return _QUOTED.findall(found.group(1))


def integration_ungated() -> list[str]:
    found = _PYTHON_SET.search(INTEGRATION.read_text(encoding="utf-8"))
    assert found is not None, (
        f"no UNGATED frozenset found in {INTEGRATION.name}; the pattern no longer matches"
    )
    return _QUOTED.findall(found.group(1))


def test_both_lists_are_found_and_are_not_empty() -> None:
    """Guard the guard. Two empty lists are equal, and that is the failure mode here."""

    assert len(vitest_ungated()) >= 2, "the vitest equality parsed to fewer than two items"
    assert len(integration_ungated()) >= 2, "the integration set parsed to fewer than two items"
    # Anchored on the dashboard, which has been ungated since the navigation existed.
    assert "/" in vitest_ungated() and "/" in integration_ungated()


def test_the_two_lists_agree() -> None:
    """**The gate the pointer was not.**

    One rule, two suites, and one of them skips silently without a database — so a divergence lives
    until somebody runs the integration suite with the variable set. That is how both slice 1 and
    slice 10 shipped a mismatch to CI.
    """

    vitest = set(vitest_ungated())
    integration = set(integration_ungated())

    assert vitest == integration, (
        "the two copies of the ungated-navigation rule disagree.\n"
        f"  {VITEST.name}: {sorted(vitest)}\n"
        f"  {INTEGRATION.name}: {sorted(integration)}\n"
        "Widening one without the other is how this rule has drifted twice. Neither is the source "
        "— update both, or make the reason they differ explicit here."
    )
