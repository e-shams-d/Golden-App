"""Every published operation is reachable from a screen, or listed with the reason it is not.

M11 Screens slice 8, and the last obligation the screens plan carries.

**Written against the operations that exist**, not against the screens this plan added. That is the
only reason `TRACE-SCREENS-001` caught `/login` unswept since M3, and the same rule applies one
level up: a gate that asks "did the slices build what they said" answers a question nobody needed,
because the plan is the thing being checked.

## Three ways an operation is reachable

**Literally** — a screen names its path. Most operations.

**Dynamically** — the path is built from a value the server supplied. The sixteen queues are the
whole reason this category exists: slice 2 deliberately removed the list of queue names from the
frontend, so `/queues/new-requests` appears in no `.ts` file and never should. Asserting literal
reachability there would push the registry copy back into the applications, which is the drift that
decision removed. So the rule is declared once, and it names the mechanism rather than the paths.

**Not at all** — and then it is listed below with why. That list is the point of this file.

## What the list is for

`NO_SCREEN` is not an allowlist. Every entry says what a screen would need, and several name the
decision that blocks one. Read together it is the honest answer to "how much of this system can a
person actually use", which is a question the milestone's own Definition of Done asks and which no
other gate in this repository can answer.

Covers: TRACE-SCREENS-002.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.queues.registry import BUILT

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPOSITORY_ROOT / "services" / "backend" / "openapi" / "v1.json"
APPS = REPOSITORY_ROOT / "apps"

# Operations reached by a path the frontend builds from server data rather than writes down.
#
# **Each entry names the mechanism and the file that implements it**, so the exemption is
# checkable: `test_every_dynamic_rule_still_has_its_mechanism` fails when the mechanism goes.
# Without that, "it is reached dynamically" is a sentence anybody can write about anything.
DYNAMIC: dict[str, tuple[str, str]] = {
    "/api/v1/queues/{name}": (
        "apps/admin-web/src/queues.ts",
        "the sixteen queue paths are built from `GET /api/v1/queues`, which slice 2 introduced "
        "precisely so this application would not hold a list of queue names. A literal path here "
        "would be the registry copy that decision removed.",
    ),
}

# Operations no screen reaches, each with what a screen would need — and, where one exists, the
# decision that blocks it.
#
# **Not an allowlist.** An entry is a claim about the system's reach, and the ones that name a
# blocking decision expire when it is made.
NO_SCREEN: dict[tuple[str, str], str] = {
    # --- infrastructure, and no screen is intended -----------------------------------------------
    ("GET", "/api/v1/health/live"): (
        "liveness, consumed by the orchestrator. A screen would be a page about whether the page "
        "can load."
    ),
    ("GET", "/api/v1/health/ready"): "readiness, consumed by the orchestrator rather than a person",
    ("GET", "/api/v1/health/dependencies"): (
        "operations token, not a session — `test_m3_definition_of_done.py` classifies it "
        "`OPERATIONS`. The caller is an operator with a shell."
    ),
    (
        "GET",
        "/api/v1/health/workers",
    ): "an operations token guards it, like the health reads above: the caller is an "
    "operator with a shell rather than a person with a browser",
    (
        "GET",
        "/api/v1/operations/background-processing",
    ): "an operations token guards it, like the health reads above: the caller is an "
    "operator with a shell rather than a person with a browser",
    (
        "GET",
        "/api/v1/operations/release-evidence",
    ): "an operations token guards it, like the health reads above: the caller is an "
    "operator with a shell rather than a person with a browser",
    ("POST", "/api/v1/center-profile/rename"): (
        "operations token, as above — and `test_preconditions_have_a_source.py` already records "
        "it as having no read to take a precondition from, for the same reason"
    ),
    # --- authentication flows with no screen yet -------------------------------------------------
    ("POST", "/api/v1/auth/admin/recover-password"): (
        "the far side of an administrative reset. A screen needs the recovery token flow M3 left "
        "to the operator, and building one without deciding how a person receives that token "
        "would be a form with nothing to type into it."
    ),
    ("POST", "/api/v1/auth/change-password"): (
        "no screen changes a password yet. The route is complete and guarded by the current "
        "password; what is missing is a settings surface, which no slice has owned."
    ),
    # --- bank configuration ----------------------------------------------------------------------
    ("GET", "/api/v1/bank-profiles"): "bank configuration has no screen; see the POST below",
    ("POST", "/api/v1/bank-profiles"): (
        "creating a bank profile is a configuration act performed once per bank. M2 built it for "
        "the seeding path and no slice has owned a configuration surface."
    ),
    (
        "GET",
        "/api/v1/bank-accounts",
    ): "bank configuration, like the profile routes above: performed once per bank and "
    "owned by no slice",
    (
        "POST",
        "/api/v1/bank-accounts",
    ): "bank configuration, like the profile routes above: performed once per bank and "
    "owned by no slice",
    ("POST", "/api/v1/bank-profile-versions/{version_id}/activate"): (
        "**blocked rather than unbuilt.** `bank_profile.activate_version` is granted to no role in "
        "`permission_catalog.yaml`, so a screen behind it would refuse every caller — the shape "
        "this project refuses to build and already carries once."
    ),
    # --- the statement import path ---------------------------------------------------------------
    ("GET", "/api/v1/bank-statements"): "the statement import path; see the POST below",
    ("POST", "/api/v1/bank-statements"): (
        "**blocked on the bank.** The owner has confirmed the bank returns no Excel, so M10's "
        "parser has no input in practice and a screen would be a surface for a flow that cannot "
        "start. Recorded in the M11 screens plan against slice 6."
    ),
    (
        "GET",
        "/api/v1/bank-statements/{statement_id}",
    ): "part of the statement import path above, and blocked by the same bank question",
    (
        "GET",
        "/api/v1/bank-statements/{statement_id}/import-runs",
    ): "part of the same unbuilt surface as the operation above it",
    (
        "POST",
        "/api/v1/bank-statements/{statement_id}/import-runs",
    ): "part of the same unbuilt surface as the operation above it",
    # --- the bundle and segment path -------------------------------------------------------------
    ("GET", "/api/v1/receipt-segments/{segment_id}/matching-candidates"): (
        "the automatic matching path over bank result bundles. A screen needs the segment viewer "
        "M8 built the backend for and no slice has owned; the *manual* judgement it feeds — which "
        "row proves a claim — is the incoming payment match surface, which slice 6 built."
    ),
    (
        "POST",
        "/api/v1/receipt-segments/{segment_id}/matching-candidates",
    ): "part of the same unbuilt surface as the operation above it",
    (
        "POST",
        "/api/v1/matching-candidates/{candidate_id}/accept-for-confirmation",
    ): "part of the same unbuilt surface as the operation above it",
    (
        "POST",
        "/api/v1/matching-candidates/{candidate_id}/reject",
    ): "part of the same unbuilt surface as the operation above it",
    ("POST", "/api/v1/bank-result-bundles/{bundle_id}/batch-links"): (
        "links a result bundle to the batch it answers. The bundle screens exist; this operation "
        "is performed by the import path rather than by a person, and no slice has decided "
        "whether a human should ever do it by hand."
    ),
    # --- evidence -------------------------------------------------------------------------------
    ("POST", "/api/v1/evidence-links"): (
        "confirming an evidence link. Slice 4's payment confirmation offers the *reason* evidence "
        "is unavailable rather than a link, because linking needs the file browser M4 built the "
        "backend for and no slice has owned."
    ),
    (
        "POST",
        "/api/v1/evidence-links/{link_id}/replace",
    ): "part of the same unbuilt surface as the operation above it",
    (
        "POST",
        "/api/v1/evidence-links/{link_id}/void",
    ): "part of the same unbuilt surface as the operation above it",
    # M11 Screens slice 9 built the review task screen, so the six manual-review operations
    # left this list — which is what a closed entry looks like here: a deletion rather than an
    # edit. `test_no_recorded_operation_has_quietly_gained_a_screen` is what would have caught
    # them being left behind.
    # --- the report ----------------------------------------------------------------------------
    ("GET", "/api/v1/reports/queue-summary"): (
        "**superseded by a better surface rather than unbuilt.** The dashboard shows the same "
        "counts through `GET /api/v1/queues`, which slice 2 added because this report is guarded "
        "by `report.read` — a grant `warehouse_operator` and `technical_admin` do not hold, and "
        "between them they hold four of the sixteen queues. A screen behind this route would "
        "refuse the two roles whose whole day is a queue."
    ),
}


def published_operations() -> dict[tuple[str, str], str]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    found: dict[tuple[str, str], str] = {}
    for path, operations in contract["paths"].items():
        for method, operation in operations.items():
            if isinstance(operation, dict):
                found[(method.upper(), path)] = operation.get("operationId", "")
    return found


def frontend_source() -> str:
    """Every TypeScript file in both applications, concatenated.

    Both, because an operation reachable from either is reachable — `UI-ISO-001` is about neither
    bundle naming the *other's* paths, not about a path appearing only once.
    """

    parts: list[str] = []
    for app in ("admin-web", "trader-pwa"):
        for sub in ("app", "src", "components"):
            directory = APPS / app / sub
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*.ts*")):
                parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def literal_segments(path: str) -> list[str]:
    """The parts of a path a screen would have to write down. `api` and `v1` are the base URL."""

    return [
        part
        for part in path.split("/")
        if part and not part.startswith("{") and part not in {"api", "v1"}
    ]


def is_dynamic(path: str) -> bool:
    """Does a declared dynamic rule cover this path?"""

    for pattern in DYNAMIC:
        prefix = pattern.split("{", 1)[0]
        if path.startswith(prefix):
            return True
    return False


def test_the_reader_finds_the_operations_and_the_screens() -> None:
    """Guard the guard. Everything below is vacuous without these.

    A contract that parsed to nothing, or a frontend read that returned nothing, would make every
    operation look unreachable — which fails loudly — or, worse, make the `NO_SCREEN` list look
    complete when it is the only thing left.
    """

    operations = published_operations()
    assert len(operations) >= 90, f"only {len(operations)} operations parsed from the contract"

    source = frontend_source()
    assert len(source) > 50_000, f"only {len(source)} characters of frontend source were read"
    # Anchored on two paths that are definitely written down, so a read returning the wrong files
    # would not satisfy the length check alone.
    assert "/payment-requests" in source and "/gold-sale-orders" in source


def test_every_operation_is_reachable_or_recorded() -> None:
    """**The obligation.** An operation with no screen and no entry is a surface nobody can use.

    The failure this prevents is the one the whole milestone is about: a backend that works and a
    person who cannot reach it. It has happened here before — every command slices 4 to 7 built had
    existed for a milestone with nothing calling it.
    """

    source = frontend_source()
    orphaned: dict[str, str] = {}

    for (method, path), operation in sorted(published_operations().items()):
        if (method, path) in NO_SCREEN or is_dynamic(path):
            continue
        parts = literal_segments(path)
        if parts and all(part in source for part in parts):
            continue
        orphaned[f"{method} {path}"] = operation

    assert orphaned == {}, (
        "these operations are published and no screen reaches them:\n"
        + json.dumps(orphaned, indent=2)
        + "\nBuild a screen, or add an entry to NO_SCREEN saying what one would need."
    )


def test_no_recorded_operation_has_quietly_gained_a_screen() -> None:
    """The other direction, and the reason this list does not only grow.

    An entry whose paths a screen now names is excusing nothing, and the next person reading the
    list would believe a surface is unreachable when it is not. The same shape as
    `test_no_recorded_gap_has_quietly_been_closed` and the pending-obligation gate.
    """

    source = frontend_source()
    covered: list[str] = []

    for method, path in NO_SCREEN:
        parts = literal_segments(path)
        if parts and all(part in source for part in parts):
            covered.append(f"{method} {path}")

    assert covered == [], (
        f"these are recorded as having no screen and a screen now names them: {covered}. Delete "
        "the entry — a stale one is a claim that part of the system is unreachable when it is not."
    )


def test_no_entry_names_an_operation_that_is_gone() -> None:
    """A stale entry excuses nothing forever, and hides the next real gap."""

    operations = set(published_operations())
    stale = sorted(
        f"{method} {path}" for method, path in NO_SCREEN if (method, path) not in operations
    )

    assert stale == [], f"these entries name operations the contract no longer publishes: {stale}"


def test_every_entry_says_what_a_screen_would_need() -> None:
    """An entry with no reason is an allowlist row.

    Asserted on the text because that is all this file can check — but the difference between "no
    slice has owned this" and "a decision blocks it" is the difference between work and a question,
    and only a sentence carries it.
    """

    for key, reason in NO_SCREEN.items():
        assert len(reason) > 30, f"{key} is recorded with no explanation worth reading"


def test_every_dynamic_rule_still_has_its_mechanism() -> None:
    """**What keeps `DYNAMIC` from being a hole.**

    "It is reached dynamically" is a sentence anybody can write about anything. Each rule names the
    file that builds the path, and that file has to still build it — otherwise sixteen operations
    would be exempt because of a mechanism somebody deleted.
    """

    for pattern, (module, reason) in DYNAMIC.items():
        path = REPOSITORY_ROOT / module
        assert path.is_file(), f"{pattern} is exempt via {module}, which does not exist"
        source = path.read_text(encoding="utf-8")
        prefix = pattern.split("{", 1)[0].removeprefix("/api/v1")
        assert prefix in source, (
            f"{pattern} is exempt because {module} builds the path, and that file no longer "
            f"mentions {prefix!r}"
        )
        assert len(reason) > 30, f"{pattern}'s dynamic rule has no explanation worth reading"


def test_the_dynamic_queue_rule_covers_every_built_queue() -> None:
    """The rule claims sixteen paths. It must claim exactly the ones that exist.

    A queue added to the registry is a route published under the same prefix, so it is covered
    automatically — which is correct and is also why the count is asserted here: if `BUILT` ever
    shrank to nothing, the rule would still be "true" and would be covering nothing.
    """

    published = {path for _method, path in published_operations() if "/queues/" in path}
    assert len(published) == len(BUILT), (
        f"{len(published)} queue routes are published against {len(BUILT)} built queues"
    )
    assert len(BUILT) >= 16, f"only {len(BUILT)} queues are built; the dynamic rule covers little"


def test_the_recorded_list_is_not_most_of_the_system() -> None:
    """A ceiling, so this file cannot become the place unreachable surfaces go to be forgotten.

    Not a floor on screens — that number moves for good reasons — but a statement that the majority
    of what the backend publishes is usable. If a later milestone pushes this over, the honest
    response is to build screens rather than to raise the number.
    """

    operations = published_operations()
    recorded = len(NO_SCREEN)
    assert recorded < len(operations) / 2, (
        f"{recorded} of {len(operations)} operations are recorded as having no screen. More than "
        "half the published surface would be unreachable, which is a milestone's worth of work "
        "rather than a list."
    )
