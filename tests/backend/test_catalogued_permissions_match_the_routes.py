"""`command_catalog.yaml` names a permission per command. Nothing checked it against the routes.

**Found on 2026-09-11, three days after the owner granted `bank_profile.activate_version`.** That
command's catalogue row still read `"permission": []` with a `permission_gap` saying no
action-specific permission existed — written truthfully in M2, seeded away by `20260816_0014`,
granted by `20260914_0045`, and never once contradicted by a test. A governance document was
telling anybody who read it that the activation is unreachable, while the route was guarded by the
permission it claimed did not exist.

Two gates already sit either side of this and neither covers it:

- `test_rbac_seed_matches_catalogue.py` holds `permission_catalog.yaml` against the seeding
  migrations — *which roles hold which permission*;
- `test_permission_guards.py` holds every route to declaring *some* permission or being listed.

So "does this route require what the catalogue says the command requires" fell between them, in
both directions: a route could ask for the wrong grant, and a catalogue row could name a grant the
route never checks. That is the gap this file closes.

**The comparison is by route, not by id.** A command id is a name somebody chose; a method and path
are what a caller actually reaches. Matching on the id would have compared rows to themselves.

Covers: CI-CATALOGUE-002.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMANDS = REPOSITORY_ROOT / "docs" / "governance" / "command_catalog.yaml"

# Rows whose declared permission is deliberately not the route's guard, each with the reason.
#
# **An entry is a claim, not an excuse.** `test_no_exemption_describes_a_matching_row` fails when
# one of these stops differing, so an exemption cannot outlive the disagreement it documents — and
# a *new* disagreement is a failure rather than a silent addition, which is the whole point.
#
# These four are what this gate found the day it was written. None is a hole: each is the catalogue
# and the route describing the same control from different sides. They are recorded rather than
# reconciled because reconciling them means editing an approved-provisional governance document,
# and the four need four different decisions.
EXEMPT: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/payment-requests/{}/submit"): (
        "the route admits `payment_request.create_internal` as an **alternative** to "
        "`payment_request.submit`, so a staff member creating a request on a trader's behalf can "
        "submit it in the same act. `declared_permissions` flattens alternatives into one set, so "
        "the route reads as requiring both; a caller needs either. The catalogue names the "
        "trader's, which is the command's subject."
    ),
    ("POST", "/api/v1/gold-sale-orders/{}/dispatches"): (
        "the same shape: `gold_sale.dispatch_override` is an alternative the route admits, not a "
        "second requirement. The catalogue names the ordinary grant."
    ),
    ("POST", "/api/v1/bank-result-bundles"): (
        "the catalogue names `file.upload` beside `bank_result_bundle.upload` because uploading a "
        "bundle does create a file object. The route requires the bundle grant alone, and "
        "`20260801_0008` gives both to the same roles — so nobody is admitted who would be refused "
        "by the stricter reading. Worth revisiting if the two grants ever diverge, which is what "
        "this entry is for."
    ),
    ("POST", "/api/v1/auth/sessions/{}/revoke"): (
        "**the catalogue describes a command that was not built.** Its row names "
        "`auth.session.revoke_all` and `auth.session.revoke_own`; the implemented route revokes "
        "the caller's *own* session and is scoped by ownership rather than by a permission — "
        "`test_permission_guards.py` lists it as such, and `test_m3_definition_of_done.py` "
        "classifies it `OWNERSHIP`. Revoking somebody else's session has no route. Recorded here "
        "rather than edited because deleting a permission from an approved catalogue is an M0 act."
    ),
}

# Catalogued addresses the application does not serve, each with why. Distinct from a `path_note`
# on the row itself: these are commands whose absence is a milestone boundary rather than a
# decision about the row, and listing them here keeps the governance document free of scaffolding
# that describes this repository's schedule.
UNSERVED: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/bank-profile-versions/{}/mappings"): "bank mappings are Phase 1B",
    ("POST", "/api/v1/bank-mappings/{}/activate"): "bank mappings are Phase 1B",
    ("PUT", "/api/v1/settings/feature-flags"): (
        "the feature-flag surface is unbuilt; the catalogue row carries "
        "`recent_auth: policy_pending_for_sensitive_flags` and is blocked on that policy"
    ),
    ("POST", "/api/v1/retention-policies/proposals"): "retention is blocked by ADR-004/ADR-005",
    ("POST", "/api/v1/retention-policies/{}/approve"): "retention is blocked by ADR-004/ADR-005",
    ("POST", "/api/v1/retention-policies/{}/activate"): "retention is blocked by ADR-004/ADR-005",
    ("POST", "/api/v1/legal-holds"): "legal holds are blocked by the same retention ADRs",
    ("POST", "/api/v1/legal-holds/{}/release"): (
        "legal holds are blocked by the same retention ADRs"
    ),
}


def catalogue_rows() -> list[dict[str, Any]]:
    return list(json.loads(COMMANDS.read_text(encoding="utf-8"))["commands"])


_PARAMETER = re.compile(r"\{[^}]*\}")


def shape(method: str, path: str) -> tuple[str, str]:
    """A route's identity for comparison: its method and its path with parameter *names* erased.

    **The names differ and should not matter.** `command_catalog.yaml` writes
    `/payment-requests/{request_id}/submit` where the application serves
    `/payment-requests/{payment_request_id}/submit`. Same address, same command, different word
    inside the braces — and the first version of this file called six served routes "not served"
    for exactly that. A parameter's spelling is a local variable name; what a caller reaches is the
    shape.

    Erasing them does lose one thing: a row that named `/x/{a}/y` could match a route serving
    `/x/{b}/y` with a different meaning. No such pair exists here, and the alternative — treating a
    rename as a missing endpoint — misreports a real surface as absent, which is the more dangerous
    direction for a file whose whole job is telling you what is real.
    """

    return method.upper(), _PARAMETER.sub("{}", path)


def route_guards(app: Any) -> dict[tuple[str, str], set[str]]:
    """Every served route with the permission codes its `requires(...)` dependencies check.

    **Both halves are imported from `test_permission_guards.py` rather than reimplemented.**
    `routes_of` walks a private FastAPI structure — `include_router` stores a wrapper whose
    children carry unprefixed paths — and `declared_permissions` reads the guard closure's cell
    contents. Neither is public API. A second copy of either would keep *running* after FastAPI
    changed and quietly return nothing, and this file would then report the whole catalogue as
    wrong rather than reporting that it can no longer see the application. One reader, one failure;
    the floor in `test_the_reader_finds_routes_and_their_permissions` is what proves it still sees.

    A flat `app.routes` returns three entries here, which is how that failure looks.
    """

    from test_permission_guards import declared_permissions, routes_of

    return {
        shape(method, path): declared_permissions(route) for method, path, route in routes_of(app)
    }


@pytest.fixture
def guards(app_factory: Any) -> dict[tuple[str, str], set[str]]:
    """Function-scoped, because `app_factory` is. Building the application four times costs
    milliseconds and the alternative is a scope mismatch that reads as a collection error."""

    app, _runtime, _settings = app_factory()
    return route_guards(app)


def test_the_reader_finds_routes_and_their_permissions(
    guards: dict[tuple[str, str], set[str]],
) -> None:
    """Guard the guard. Every comparison below is vacuous if this returns nothing.

    Two anchors rather than a count: a route that certainly has a permission, and the shape of the
    whole map. A reader that silently returned empty sets would make every row below "the route
    requires nothing", and the assertions would then read as catalogue problems.
    """

    assert len(guards) >= 90, f"only {len(guards)} routes were read from the application"

    known = guards.get(shape("POST", "/api/v1/bank-profile-versions/{version_id}/activate"))
    assert known == {"bank_profile.activate_version"}, (
        f"the reader does not see the activation route's guard: {known}"
    )
    assert sum(1 for codes in guards.values() if codes) >= 70, (
        "almost no route appears to declare a permission, so the reader is not finding them"
    )


def test_every_catalogued_command_requires_what_its_route_requires(
    guards: dict[tuple[str, str], set[str]],
) -> None:
    """The obligation. A row that names a permission the route does not check is a document
    describing a system that does not exist.

    Rows whose `path` is `TBD`, or whose address is not served, are skipped here and covered by
    `test_no_row_names_an_address_that_is_not_served` below — the two failures need different
    sentences, and a single test would report the wrong one.
    """

    wrong: list[str] = []
    for row in catalogue_rows():
        key = shape(str(row.get("method", "")), str(row.get("path", "")))
        if key in EXEMPT or key not in guards:
            continue
        catalogued = set(row.get("permission") or [])
        if catalogued != guards[key]:
            wrong.append(
                f"{key[0]} {key[1]}\n"
                f"      catalogue: {sorted(catalogued) or '(none)'}\n"
                f"      route:     {sorted(guards[key]) or '(none)'}"
            )

    assert wrong == [], (
        "these commands and their routes disagree about what a caller must hold:\n  "
        + "\n  ".join(wrong)
        + "\nFix whichever is wrong. If the difference is deliberate, add it to EXEMPT with the "
        "reason — but a permission the route does not check is not a control."
    )


def test_no_row_names_an_address_that_is_not_served(
    guards: dict[tuple[str, str], set[str]],
) -> None:
    """A catalogued path nothing serves, recorded rather than silently tolerated.

    `TBD` is honest — the catalogue uses it for commands whose address M0 has not chosen. A
    concrete path that 404s is different: it reads as an implemented contract. `bank_profile.
    create_version` carries one (`POST /bank-profiles/{profile_id}/versions`, never served: the
    profile create makes version 1 and nothing creates a second), and its row now says so in a
    `path_note`.

    So the rule is: name a real address, say `TBD`, or explain the absence in the row itself.
    """

    unserved: list[str] = []
    for row in catalogue_rows():
        method = str(row.get("method", "")).upper()
        path = str(row.get("path", ""))
        key = shape(method, path)
        if method == "TBD" or path == "TBD" or key in guards:
            continue
        if key not in UNSERVED and not row.get("path_note"):
            unserved.append(f"{row['id']}: {method} {path}")

    assert unserved == [], (
        "these rows name an address the application does not serve, with no `path_note` on the "
        f"row and no entry in UNSERVED saying why: {unserved}"
    )


def test_no_unserved_entry_names_a_route_that_now_exists(
    guards: dict[tuple[str, str], set[str]],
) -> None:
    """The other direction. A command built after being recorded as unbuilt must leave this list.

    Same shape as `test_no_recorded_operation_has_quietly_gained_a_screen`: a list of absences only
    stays honest if closing one is a deletion.
    """

    built = sorted(f"{key[0]} {key[1]}" for key in UNSERVED if key in guards)

    assert built == [], (
        f"these are recorded as unserved and the application now serves them: {built}"
    )


def test_no_exemption_describes_a_matching_row(
    guards: dict[tuple[str, str], set[str]],
) -> None:
    """An exemption outliving its disagreement is the failure this repository keeps meeting.

    `.trivyignore.yaml`'s own header states the rule for its domain — "an exception whose stated
    reason has expired is worse than none, because it still reads as reviewed" — and it applies
    here unchanged.
    """

    stale: list[str] = []
    rows = {shape(str(r.get("method", "")), str(r.get("path", ""))): r for r in catalogue_rows()}
    for key in EXEMPT:
        row = rows.get(key)
        if row is None:
            stale.append(f"{key[0]} {key[1]}: no catalogue row")
            continue
        if key not in guards:
            stale.append(f"{key[0]} {key[1]}: not served")
            continue
        if set(row.get("permission") or []) == guards[key]:
            stale.append(f"{key[0]} {key[1]}: the catalogue and the route now agree")

    assert stale == [], f"exemptions that no longer describe a difference: {stale}"


def test_every_catalogued_permission_is_one_the_catalogue_of_permissions_declares() -> None:
    """A command may not require a name `permission_catalog.yaml` has never heard of.

    `declare()` already refuses one at import time for a *route*; this is the same rule for the
    document. Without it a row could require `bank_profile.activate` — plausible, adjacent to a
    real name, and held by nobody — and every other test here would pass, because the route would
    be exempt for naming something different.
    """

    import yaml

    catalogue = yaml.safe_load(
        (REPOSITORY_ROOT / "docs" / "governance" / "permission_catalog.yaml").read_text(
            encoding="utf-8"
        )
    )
    known: set[str] = set()
    for group in (catalogue.get("permission_groups") or {}).values():
        for member in (group or {}).values():
            if isinstance(member, dict):
                known.update(member.keys())

    assert len(known) >= 100, f"only {len(known)} permissions parsed from the catalogue"

    invented = sorted(
        {
            code
            for row in catalogue_rows()
            for code in (row.get("permission") or [])
            if code not in known
        }
    )

    assert invented == [], (
        f"these commands require permissions `permission_catalog.yaml` does not declare: {invented}"
    )
