"""Every citation in a handoff plan's source table must resolve to a real, non-blank line.

Written after the M9 plan shipped its first draft with nine citations pointing at blank
lines. A plan's whole claim is that `§17 :1131` can be checked in seconds; a citation that
lands on whitespace costs more than no citation at all, because it looks checked.

Three assertions, and the third is the one that caught the real mistake:

1. **Every cited line exists and is not blank.** A line number past the end of the file, or
   on a blank separator, is a citation nobody can follow.
2. **The two columns agree.** The table carries a short form (`§17 :1131`) and a full one
   (`15_Agent_Implementation_Plan.md:1131`). The first draft was corrected with a
   find-and-replace over the short form alone, which left every corrected row naming two
   different lines — internally inconsistent and impossible to notice by reading.
3. **Every line number used in the prose resolves somewhere.** Correcting the table alone
   left three stale numbers in the body, because two were **line-wrapped** (`§17\n:1186`)
   and one was capitalised (`Doc 04`), so neither the find-and-replace nor a careful reading
   found them. Prose citations are *not* required to appear in the table — M8 legitimately
   cites ten lines it does not tabulate — so the rule is weaker and still catches the bug: a
   number in the prose must land on a non-blank line of **some** document the table
   references. A stale number almost always points into whitespace or past the end, because
   the corrected line moved for a reason.

Plans with no source table are reported and skipped. The table is an M8-era convention;
M2 through M7 predate it and are not defective for lacking one.

Run: python3 scripts/check-plan-citations.py docs/handoff/M9_IMPLEMENTATION_PLAN.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = REPOSITORY_ROOT / "Implementation Docs"

# `| §17 `:1131` | `15_Agent_Implementation_Plan.md:1131` | the seven validations |`
ROW = re.compile(
    r"^\|\s*(?P<short>[^|]*?`:(?P<short_line>\d+)`)\s*\|"
    r"\s*`(?P<file>[A-Za-z0-9_]+\.md):(?P<full_line>\d+)`\s*\|"
)


def resolve(name: str) -> Path | None:
    matches = sorted(DOCUMENTS.rglob(name))
    return matches[0] if matches else None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    plan = Path(argv[1])
    if not plan.is_absolute():
        plan = REPOSITORY_ROOT / plan
    rows = [
        match
        for line in plan.read_text(encoding="utf-8").splitlines()
        if (match := ROW.match(line))
    ]

    # A plan with no source table is out of scope rather than broken: the table is an
    # M8-era convention and M2-M7 predate it. Reported so that a *regression* — M9 losing
    # its table, or the row pattern drifting — is visible rather than silently green, which
    # is the failure this repository has seen more often than any other.
    if not rows:
        print(f"{plan.name}: no source table, skipped")
        return 0

    problems: list[str] = []
    cache: dict[str, list[str]] = {}

    for row in rows:
        name = row.group("file")
        short_line = int(row.group("short_line"))
        full_line = int(row.group("full_line"))

        if short_line != full_line:
            problems.append(
                f"{row.group('short').strip()} names line {short_line} but its full "
                f"citation names {full_line}"
            )
            continue

        if name not in cache:
            path = resolve(name)
            if path is None:
                problems.append(f"{name} is not under {DOCUMENTS.name}/")
                cache[name] = []
                continue
            cache[name] = path.read_text(encoding="utf-8").splitlines()

        lines = cache[name]
        if not lines:
            continue
        if full_line < 1 or full_line > len(lines):
            problems.append(f"{name}:{full_line} is past the end ({len(lines)} lines)")
        elif not lines[full_line - 1].strip():
            problems.append(f"{name}:{full_line} is a blank line")

    # Assertion 3. Every `:NNNN` in the prose lands on a real, non-blank line of at least one
    # document the table references.
    #
    # Deliberately blind to *which* document a prose citation names: attributing it would mean
    # parsing "§17" or "doc 04" out of text that wraps across lines and varies in case, which
    # is precisely the fragility that let the stale numbers through. Resolving against the
    # union is weaker than per-document attribution and cannot be defeated by formatting.
    text = plan.read_text(encoding="utf-8")
    approved = {int(row.group("full_line")) for row in rows}
    corpus = [lines for lines in cache.values() if lines]
    used = {int(n) for n in re.findall(r"`:(\d+)`", text)}

    unresolved = []
    for number in sorted(used - approved):
        if not any(
            1 <= number <= len(lines) and lines[number - 1].strip() for lines in corpus
        ):
            unresolved.append(number)
    for number in unresolved:
        problems.append(
            f"the prose cites `:{number}`, which is blank or out of range in every document "
            "this plan's table references — most likely a number the table corrected and the "
            "prose kept"
        )

    print(
        f"{len(rows)} citations checked in {plan.name}, "
        f"{len(used)} distinct in prose, {len(used - approved)} beyond the table"
    )
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
