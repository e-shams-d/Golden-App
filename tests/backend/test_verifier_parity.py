"""CI-PARITY-001: the shell and PowerShell verifiers must gate the same things.

A developer on Windows runs `verify-native.ps1`; the shell gate and CI run
`verify-native.sh`. When those disagree, "green" means different things to different
people, and the disagreement is invisible until something ships.

**This slice produced four instances of that in a row**, which is why the file exists:

1. `tests/fixtures/` was created in slice 8 and added to no lint target list, so it
   went unlinted for two slices while both scripts reported green
2. the list is written out in both native scripts, so fixing it meant two edits
3. my own gate script had drifted from `verify-native.sh`
4. that gate script ran only the backend half of the OpenAPI check, so it reported
   green on precisely the state CI failed on

Every one is the same shape: a list written down more than once.

So the fix is structural where it can be — the lint targets now live in one file both
scripts read — and comparative where it cannot. Two scripts written in two languages
cannot share their control flow, so the stage *names* are compared instead: each pair
must announce the same set of stages.

Set, not sequence. `verify-docker.sh` declares its cleanup stages in a function near
the top and runs them last, so source order is not execution order; an ordering
assertion would fail on a script that behaves correctly.

The comparison is deliberately of announced stages rather than of commands. Commands
legitimately differ between `sh` and PowerShell; what must not differ is which gates
run. And a shared target file is what covers the case a stage-name comparison cannot
see — both scripts announcing "Running backend lint" while linting different trees is
exactly what happened.

Covers: TRACE-001.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPOSITORY_ROOT / "infra" / "scripts"
LINT_TARGETS = REPOSITORY_ROOT / "infra" / "verification" / "lint_targets.txt"

# A stage announcement, in either language. Two deliberate choices:
#
# The format string is matched as `'%s...'` rather than by spelling out the escape.
# Passing a backslash through this file, a shell heredoc and a regex is how four
# earlier attempts at pattern-matching in this slice silently matched nothing while
# reporting success.
#
# The trailing `...` is the discriminator. Both scripts already use it for stages and
# not for errors, so the convention is observed rather than imposed — and without it
# the match picks up every `>&2` failure message, which are not gates.
_SH_MESSAGE = re.compile(r"""printf\s+'%s[^']*'\s*\\?\s*\n?\s*"([A-Z][^"$]*\.\.\.)\"""")
_PS_MESSAGE = re.compile(r'Write-Host\s+"([A-Z][^"$]*\.\.\.)"')

PAIRS = [("verify-native.sh", "verify-native.ps1"), ("verify-docker.sh", "verify-docker.ps1")]


def stages(script: str) -> list[str]:
    """The stage announcements a script makes, in order.

    Messages containing a shell or PowerShell variable are skipped: those are
    per-run detail such as a version string, not a gate.
    """

    text = (SCRIPTS / script).read_text(encoding="utf-8")
    pattern = _PS_MESSAGE if script.endswith(".ps1") else _SH_MESSAGE
    return [match.group(1).strip() for match in pattern.finditer(text)]


def lint_targets() -> list[str]:
    lines = LINT_TARGETS.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


@pytest.mark.parametrize(("shell", "powershell"), PAIRS, ids=lambda value: value)
def test_the_pair_announces_the_same_stages(shell: str, powershell: str) -> None:
    """Same gates, same order, whichever script a developer runs."""

    in_shell = stages(shell)
    in_powershell = stages(powershell)

    assert in_shell, f"{shell} announces no stages; the extraction pattern is wrong"
    only_shell = [stage for stage in in_shell if stage not in in_powershell]
    only_powershell = [stage for stage in in_powershell if stage not in in_shell]

    assert (only_shell, only_powershell) == ([], []), (
        f"{shell} and {powershell} do not gate the same things.\n"
        f"  only in {shell}: {only_shell}\n"
        f"  only in {powershell}: {only_powershell}"
    )

    # Membership, not order, and that is a correctness decision rather than a
    # concession. `verify-docker.sh` declares its cleanup stages inside a function
    # near the top of the file and runs them last, so source order is not execution
    # order — an ordering assertion would be asserting something false and would fail
    # on a script that behaves correctly. What must not differ is *which* gates run.
    assert sorted(in_shell) == sorted(in_powershell)


@pytest.mark.parametrize("script", ["verify-native.sh", "verify-native.ps1"])
def test_neither_native_script_embeds_its_own_lint_target_list(script: str) -> None:
    """The structural half, and the one that catches what stage names cannot.

    Both scripts can announce "Running backend lint, type, and test gates..." while
    linting different trees. That is not a hypothetical — it is what happened, and it
    is why the list moved into a file instead of being compared between two copies.
    """

    text = (SCRIPTS / script).read_text(encoding="utf-8")

    assert "infra/verification/lint_targets.txt" in text, (
        f"{script} does not read the shared lint target list"
    )

    # Mentioning the file is not using it. A negative control set the target
    # variable to a hard-coded list while leaving the filename elsewhere in the
    # script, and an earlier version of this test stayed green — it was checking
    # that the path appeared, which a comment satisfies.
    #
    # So the check is on the ruff invocation itself: after `--config <path>`, every
    # remaining argument must be the expansion of the variable read from the file.
    # A literal path there means the list has grown a second home.
    ruff_block = text.split("ruff", 1)[-1].split("mypy", 1)[0]
    expansion = "$lintTargets" if script.endswith(".ps1") else "$lint_targets"

    assert expansion in ruff_block, (
        f"{script} does not pass the shared list to ruff; it reads the file but lints "
        "something else"
    )
    for target in lint_targets():
        assert target not in ruff_block, (
            f"{script} passes {target} to ruff as a literal; the shared file is the "
            "only place that list may live"
        )


def test_the_shared_target_list_names_only_paths_that_exist() -> None:
    """A typo here silently drops a tree from linting, which is the original failure."""

    missing = [target for target in lint_targets() if not (REPOSITORY_ROOT / target).exists()]

    assert missing == [], f"lint targets that do not exist: {missing}"


def test_every_python_tree_under_test_is_linted() -> None:
    """The gap the original failure fell through.

    A new directory of Python is only linted if somebody remembers to add it. This
    asserts the reverse: every directory holding Python that the suite imports is in
    the list, so forgetting fails here rather than two slices later.
    """

    targets = set(lint_targets())
    expected = {
        "services/backend/app",
        "services/backend/alembic",
        "services/backend/scripts",
        "tests/backend",
        "tests/integration",
        "tests/fixtures",
    }

    assert expected <= targets, f"unlinted Python trees: {sorted(expected - targets)}"


def test_every_infra_script_is_linted() -> None:
    """`infra/scripts/*.py` are gates themselves; an unlinted gate is one nobody
    checks. `m0_manifest.py` was unlinted until slice 10 for exactly that reason."""

    listed = {target for target in lint_targets() if target.startswith("infra/scripts/")}
    on_disk = {
        f"infra/scripts/{path.name}"
        for path in (REPOSITORY_ROOT / "infra" / "scripts").glob("*.py")
    }

    assert on_disk <= listed, f"unlinted infra scripts: {sorted(on_disk - listed)}"


def test_the_umbrella_script_runs_both_halves() -> None:
    """`verify.sh` is what a developer runs when they mean "everything"."""

    text = (SCRIPTS / "verify.sh").read_text(encoding="utf-8")

    assert "verify-native.sh" in text
    assert "verify-docker.sh" in text


def test_the_extraction_finds_the_stages_it_claims_to() -> None:
    """Guard the guard.

    Every comparison above passes vacuously if `stages()` returns empty lists for
    both members of a pair. Two known stage names must be found in each script.
    """

    for script in ("verify-native.sh", "verify-native.ps1"):
        found = stages(script)
        assert len(found) >= 5, f"{script}: only {len(found)} stages extracted"
        assert any("lint" in stage.lower() for stage in found)
        assert any("toolchain" in stage.lower() for stage in found)
