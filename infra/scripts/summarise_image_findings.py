"""Say, in the plain CI log, which findings failed the image scan.

Standard library only, like `validate_repository.py`, so it runs on a bare runner.

**Why this exists.** Gate 6 prints its table inside a `::group::`, which GitHub collapses. A
red gate therefore said only "Process completed with exit code 1" in the log anybody reads — and
diagnosing that twice from inference cost two full CI cycles, one of which fixed something real
(a package manager shipped into a runtime image) and did not fix the gate. A gate that cannot say
what it found is a gate that gets guessed at, and guessing at a security finding is how the wrong
thing gets changed.

**It reproduces the gate's filter rather than reporting everything.** The gating pass uses
`--ignore-unfixed`, so this prints only findings that carry a `FixedVersion`. Printing the wider set
would name advisories the gate deliberately tolerates — base-OS findings the distribution has marked
deferred or won't-fix, which cannot be acted on by rebuilding — and the reader would not know which
line to act on.

No scan is run here: the first pass per image already wrote the JSON this reads.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def findings(report: dict[str, object]) -> list[str]:
    """One block per gating finding, or nothing."""

    image = str(report.get("ArtifactName") or "unknown image")
    lines: list[str] = []
    results = report.get("Results")
    for result in results if isinstance(results, list) else []:
        if not isinstance(result, dict):
            continue
        target = str(result.get("Target") or "")
        kind = str(result.get("Class") or "")
        vulnerabilities = result.get("Vulnerabilities")
        for finding in vulnerabilities if isinstance(vulnerabilities, list) else []:
            if not isinstance(finding, dict):
                continue
            fixed = finding.get("FixedVersion")
            if not fixed:
                # The gate ignores these. Naming them here would bury the actionable line.
                continue
            title = str(finding.get("Title") or "").strip()
            lines.append(
                f"{image}\n"
                f"  {finding.get('VulnerabilityID')}  {finding.get('Severity')}\n"
                f"  package  {finding.get('PkgName')} {finding.get('InstalledVersion')}"
                f"  ->  fixed in {fixed}\n"
                f"  source   {target} ({kind})\n"
                f"  title    {title[:140]}"
            )
    return lines


def main(paths: list[str]) -> int:
    blocks: list[str] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"could not read {path}: {error}")
            continue
        if isinstance(report, dict):
            blocks.extend(findings(report))

    print()
    print("=== findings that failed this gate (a fixed version exists) ===")
    if not blocks:
        # Said plainly rather than left blank. An empty summary beside a failing gate means the
        # failure came from somewhere this script does not look — a scan that errored rather than
        # found something, most likely — and that is a different problem from a vulnerability.
        print("none found in the JSON reports, so the gate failed for another reason:")
        print("check whether a trivy invocation itself errored above.")
        return 0
    for block in blocks:
        print(block)
    print(f"=== {len(blocks)} finding(s) to act on ===")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
