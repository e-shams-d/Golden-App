"""Emit the M2-supplyable release evidence as one durable artifact.

The fifteen-item release evidence set is otherwise assembled by hand, and four of
its fields can only be transcribed — which means a release candidate is accepted on
evidence nobody can reproduce. This writes them instead.

**Each field comes from whoever actually knows it**, and that split is the design:

* The **running instance** answers for its own identity, the Alembic revision its
  database records, and the feature-flag snapshot. Read over HTTP from
  `/api/v1/operations/release-evidence`, never from `alembic/versions/`. The
  repository says what *should* be deployed; the instance says what *is*, and the
  difference between them is the failure a release gate exists to catch.
* The **test run** answers for its own identifier, the fixture set versions and the
  test data-set version. Those live in the repository because that is where they are
  defined.
* The **build** answers for image digests, which reach this script as environment
  variables because only the pipeline that built them knows them.

**A missing field is recorded as missing, never omitted.** `restore_drill` stays
unfilled with its reason: ADR-004 is open, so no backup or restore claim may be made
at M2, and an evidence set that silently lacks the field reads as complete. Emitting
`null` with a stated reason is the difference between a gap and an oversight.

Nothing here falls back to reading the revision from the repository if the instance
is unreachable. A fallback would produce a plausible artifact describing a deployment
nobody verified, which is worse than no artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPOSITORY_ROOT / "tests" / "fixtures"

# Fields the evidence set requires that M2 cannot supply, with the reason. Emitted
# as null with the reason attached rather than left out.
UNFILLABLE_AT_M2: dict[str, str] = {
    "restore_drill": (
        "ADR-004 is Open: no backup or restore claim may be made at M2, so no "
        "restore drill has been performed. This field stays null until that "
        "decision is approved and a drill is run."
    ),
    "image_signature": (
        "PKG-001 is Open: the signing authority for release artifacts is not "
        "decided, so no signature exists to record."
    ),
    "performance_p95": (
        "Recorded separately with its data volume and environment. A latency "
        "figure without both is not acceptable evidence, and this script has "
        "neither to hand."
    ),
}

# The same treatment for M3's two, kept in a separate dictionary so a reader can tell which
# milestone owes which. Merged into `unfilled` on the way out.
UNFILLABLE_AT_M3: dict[str, str] = {
    "assurance_factor": (
        "ADR-009 is Open: `password` is the only registered step-up factor, and which "
        "factor a production deployment requires depends on operational facts — SMS "
        "deliverability in Iran, whether the people holding manager authority carry "
        "smartphones — that are the owner's knowledge rather than a technical judgement. "
        "M3 owed the interface, which exists, so adding a factor is a registration rather "
        "than a rewrite. The choice itself is not made and is not implied here."
    ),
    "resolved_permissions_from_instance": (
        "The running instance does not publish the permission set it actually resolves. "
        "Adding that to /api/v1/operations/release-evidence would change a published "
        "schema, and the oasdiff breaking-change gate's waiver process is still an "
        "unresolved TODO(governance). `authorization.catalogue_digest` below is read from "
        "the repository and answers a different question — what the deployment was built "
        "to grant, not what it grants. Filing the repository's answer under the "
        "instance's name is exactly the substitution this script refuses for the Alembic "
        "revision, and it would be no more honest here."
    ),
}


class EvidenceError(RuntimeError):
    """The artifact cannot be produced honestly. Never a partial write."""


def fetch_instance_evidence(base_url: str, token: str, *, timeout: float) -> dict[str, Any]:
    """Ask the running instance what it is and what schema it is on.

    Raises rather than degrading. An artifact that says "revision unknown" would be
    filed as evidence and read as though the check had been done.
    """

    url = f"{base_url.rstrip('/')}/api/v1/operations/release-evidence"
    request = urllib.request.Request(url, headers={"X-Operations-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise EvidenceError(
            f"the instance at {base_url} answered {error.code} for the release-evidence "
            "path. A 403 means the operations token is wrong; a 404 means the running "
            "build predates this endpoint, which is itself the deployment mismatch this "
            "artifact exists to detect."
        ) from error
    # `URLError` covers refusal and DNS failure. `TimeoutError` and the wider
    # `OSError` cover an instance that accepts the connection and then hangs, and a
    # network that drops the packets — both reach here as a bare socket error rather
    # than as a `URLError`, so catching only the latter would let the script raise
    # something the caller does not recognise as "no evidence".
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise EvidenceError(
            f"the instance at {base_url} did not answer ({reason}). This script does "
            "not fall back to reading the revision from the repository: that would "
            "describe a deployment nobody verified."
        ) from error
    except json.JSONDecodeError as error:
        raise EvidenceError(
            f"the instance at {base_url} answered with something that is not JSON. "
            "Usually a proxy error page, which means the request never reached the "
            "application."
        ) from error


def fixture_versions() -> dict[str, str]:
    """The versioned synthetic fixture sets, read from where they are defined."""

    sys.path.insert(0, str(FIXTURES))
    import bank_fixtures
    import file_fixtures

    return {
        "file_fixtures": file_fixtures.FIXTURE_SET_VERSION,
        "file_fixtures_digest": file_fixtures.manifest_digest(),
        "bank_fixtures": bank_fixtures.FIXTURE_SET_VERSION,
        "bank_fixtures_digest": bank_fixtures.manifest_digest(),
    }


def authorization_state() -> dict[str, Any]:
    """What this build was constructed to grant — M3's addition to the evidence set.

    Read from `docs/governance/permission_catalog.yaml`, and labelled `repository` in
    `source_of_each_field` so nobody reads it as a statement about the running instance.
    That distinction is the whole reason `resolved_permissions_from_instance` is recorded
    as unfilled beside it: the catalogue says what the deployment *should* grant, and only
    the instance can say what it *does*.

    The digest is over the file's bytes. A permission added, removed or re-scoped changes
    it, so two release artifacts can be compared without reading either catalogue — which
    is the question an auditor actually asks about a release: did authority change.
    """

    catalogue = REPOSITORY_ROOT / "docs" / "governance" / "permission_catalog.yaml"
    raw = catalogue.read_bytes()
    text = raw.decode("utf-8")

    return {
        "catalogue_digest": hashlib.sha256(raw).hexdigest(),
        "declared_permissions": len(re.findall(r"^ {6}[a-z_]+\.[a-z_]+:", text, re.M)),
        # A role is a two-space key whose first child is `identity_domain`. Matched on the
        # child rather than on the key alone, because two-space keys appear all over this
        # file — the first attempt matched a `code:` child that roles do not have and
        # counted zero, which the floor in `test_evidence_m3_items.py` reported before this
        # artifact could ever record "0 roles declared" as if that were a fact.
        "declared_roles": len(re.findall(r"^  [a-z_]+:\n    identity_domain:", text, re.M)),
        "read_from": "docs/governance/permission_catalog.yaml, not the running instance",
    }


def ai_is_disabled(flags: list[dict[str, Any]]) -> bool:
    """Every AI-adjacent flag off, checked by name rather than by counting.

    Phase 1A forbids OCR, automatic segmentation and matching. A count of enabled
    flags would pass while the wrong one was on.
    """

    forbidden = {"ocr.enabled", "auto_segmentation.enabled", "ai_matching.enabled"}
    enabled = {flag["flag_key"] for flag in flags if flag["is_enabled"]}
    return not (forbidden & enabled)


def build_artifact(instance: dict[str, Any], *, run_id: str, moment: datetime) -> dict[str, Any]:
    flags = instance["feature_flags"]
    schema = instance["schema_state"]

    artifact: dict[str, Any] = {
        "schema_version": 1,
        "emitted_at": moment.isoformat(),
        "test_run_id": run_id,
        "source_of_each_field": {
            "instance": ["service", "version", "commit", "environment", "schema", "feature_flags"],
            # `authorization` is listed here and not under `instance`, deliberately. It is
            # the repository's answer to "what was this built to grant", and the instance's
            # answer to "what does it grant" is recorded as unfilled with its reason.
            "repository": ["fixture_versions", "test_data_set_version", "authorization"],
            "build": ["image_digests"],
        },
        "instance": {
            "service": instance["service"],
            "version": instance["version"],
            "commit": instance["commit"],
            "environment": instance["environment"],
        },
        "schema": {
            "applied_revisions": schema["applied_revisions"],
            "expected_revisions": schema["expected_revisions"],
            "matches": schema["matches"],
            "read_from": "the running instance's own database, not alembic/versions",
        },
        "feature_flags": flags,
        "ai_disabled": ai_is_disabled(flags),
        "fixture_versions": fixture_versions(),
        # One string covering both fixture sets plus the schema they load against, so
        # "which data was this run against" has a single answer.
        "test_data_set_version": None,
        "image_digests": {
            name: os.environ.get(variable)
            for name, variable in (
                ("backend", "BACKEND_IMAGE_DIGEST"),
                ("worker", "WORKER_IMAGE_DIGEST"),
                ("trader_pwa", "TRADER_PWA_IMAGE_DIGEST"),
                ("admin_web", "ADMIN_WEB_IMAGE_DIGEST"),
                ("nginx", "NGINX_IMAGE_DIGEST"),
            )
        },
        "authorization": authorization_state(),
        # Merged rather than nested, because a reader asking "what is missing from this
        # artifact" should get one answer. Which milestone owes each is recoverable from
        # the two dictionaries above; splitting the output would make the question
        # "what is missing" require reading two lists and knowing there were two.
        "unfilled": {**UNFILLABLE_AT_M2, **UNFILLABLE_AT_M3},
    }

    versions = artifact["fixture_versions"]
    artifact["test_data_set_version"] = (
        f"{versions['file_fixtures']}+{versions['bank_fixtures']}"
        f"@{'.'.join(schema['applied_revisions'])}"
    )
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EVIDENCE_BASE_URL", "http://127.0.0.1:8000"),
        help="Where the running instance is reachable.",
    )
    parser.add_argument(
        "--operations-token",
        default=os.environ.get("OPERATIONS_TOKEN", ""),
        help="The operations token the instance requires. Never logged.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Where to write the artifact.")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument(
        "--run-id",
        default=os.environ.get("GITHUB_RUN_ID") or f"local-{uuid.uuid4().hex[:12]}",
        help="Test-run identifier. Defaults to the CI run id, then to a local one.",
    )
    arguments = parser.parse_args(argv)

    if not arguments.operations_token:
        print(
            "no operations token supplied; the release-evidence path is restricted and "
            "an unauthenticated read would 403.",
            file=sys.stderr,
        )
        return 2

    try:
        instance = fetch_instance_evidence(
            arguments.base_url, arguments.operations_token, timeout=arguments.timeout
        )
        artifact = build_artifact(instance, run_id=arguments.run_id, moment=datetime.now(UTC))
    except EvidenceError as error:
        print(f"evidence not emitted: {error}", file=sys.stderr)
        return 1

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(
        (json.dumps(artifact, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    )

    print(f"evidence written to {arguments.output}")
    print(f"  run id           {artifact['test_run_id']}")
    print(f"  commit           {artifact['instance']['commit']}")
    print(f"  schema           {', '.join(artifact['schema']['applied_revisions'])}")
    print(f"  schema matches   {artifact['schema']['matches']}")
    print(f"  AI disabled      {artifact['ai_disabled']}")
    print(f"  data set         {artifact['test_data_set_version']}")
    print(f"  permissions      {artifact['authorization']['declared_permissions']} declared")
    print(f"  catalogue        {artifact['authorization']['catalogue_digest'][:16]}…")
    print(f"  unfilled fields  {', '.join(sorted(artifact['unfilled']))}")

    if not artifact["schema"]["matches"]:
        print(
            "the instance is serving against a schema it was not built for; the "
            "artifact records this rather than hiding it.",
            file=sys.stderr,
        )
        return 1
    if not artifact["ai_disabled"]:
        print("an AI-path flag is enabled, which Phase 1A forbids.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
