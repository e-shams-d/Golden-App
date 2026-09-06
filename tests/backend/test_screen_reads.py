"""Can the API feed the screens the specification describes?
`21_UI_Design_System_and_Screen_Specification.md:1256`.

M11 Screens, slice 0. **This runs before any screen is built, and that is the whole point.**

M7's screens plan gained two slices mid-build from exactly this cause: the approval view returned
eleven of §13.3's nineteen fields, and the export detail fifteen where §14 needed twenty-two. Both
were found by trying to render a screen, which is the most expensive moment to find them —
estimates for every later slice were already made against the assumption that the reads existed.

So this file asks the question first. For each specified screen it names the fields the document
requires and checks the published contract for them.

**A missing field is a finding recorded here, not a frontend problem.** The plan's §1.4 states the
rule it inherits from M7's: *a screen that needs a field the API does not return is a finding, not
a frontend fix.* `NO_OPERATION` below carries the screens with nothing at all to call.

**Both screens surveyed so far are fed.** That is a result rather than a formality: the trader
publication screen is slice 3's, and it turns out to need no backend work first — which is
exactly the kind of thing worth knowing before estimating.

**Checked against `services/backend/openapi/v1.json`, not against a live app.** The published
contract is what a frontend is written against, so a field present on a Python model and absent
from the schema is absent as far as a screen is concerned — which is a real failure mode and one a
model-reflection test would miss.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPOSITORY_ROOT / "services" / "backend" / "openapi" / "v1.json"

# Each entry: the screen, the operation a frontend would call, and the response fields §21 requires
# it to show. Field names are the *contract's*, mapped from the document's prose — the mapping is
# the judgement in this file and is why each entry cites its section.
#
# Only screens whose operation exists are listed. A screen with no operation at all is a larger
# finding than a missing field and is recorded in `NO_OPERATION` below.
SCREEN_READS: dict[str, dict[str, Any]] = {
    # §22 `:2196`. Built by M11 slice 1, and included as the control: if this file cannot confirm
    # a screen whose reads *do* exist, its findings about the others mean nothing.
    "notifications (§22)": {
        "operation": "listNotifications",
        "requires": {
            "notification_type",
            "title",
            "body",
            "entity_type",
            "entity_id",
            "status",
            "created_at",
        },
    },
    # §9.9 `:1256`. The trader's payment result screen — M9 published results and built the share
    # file; no screen renders either.
    "trader publication (§9.9)": {
        "operation": "getOwnPaymentResultPublication",
        "requires": {
            "publication_version",  # "publication version"
            "status",  # "current/superseded indicator"
            "published_at",  # "publication time"
            "summary_payload",  # "paid/failed summary", "beneficiary", "masked IBAN"
        },
    },
}

# Screens §21 specifies for which **no operation exists at all**. A larger finding than a missing
# field: there is nothing for a frontend to call.
#
# Recorded rather than asserted-absent, because "no operation" is what slices 3 to 7 exist to
# change, and a test asserting they stay missing would have to be deleted to make progress.
NO_OPERATION: dict[str, str] = {}


def contract() -> dict[str, Any]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _operation(spec: dict[str, Any], operation_id: str) -> dict[str, Any] | None:
    for methods in spec["paths"].values():
        for operation in methods.values():
            if isinstance(operation, dict) and operation.get("operationId") == operation_id:
                return operation
    return None


def _response_properties(spec: dict[str, Any], operation: dict[str, Any]) -> set[str]:
    """Every property name a 200 response can carry, resolving `$ref` and array items.

    **The depth limit was six, not three, and the control screen is what found that.** An envelope
    costs four levels before a row's own properties appear — `$ref` to the page model, its
    `properties`, the `items` array, the `$ref` to the row — so a limit of three reported the
    notification list as returning nothing but `items`, `next_cursor` and `unread_count`. Those
    fields exist and M11 built them; the walker could not see them.

    That is worth keeping in the file rather than quietly fixing: a survey whose reader is too
    shallow reports every screen as unfed, which reads as a large finding and is a bug in the
    survey. The control screen exists to catch exactly that, and did on the first run.
    """

    content = operation.get("responses", {}).get("200", {}).get("content", {})
    schema = content.get("application/json", {}).get("schema", {})
    names: set[str] = set()

    def walk(node: dict[str, Any], depth: int = 0) -> None:
        if depth > 6 or not isinstance(node, dict):
            return
        if "$ref" in node:
            key = node["$ref"].rsplit("/", 1)[-1]
            walk(spec["components"]["schemas"].get(key, {}), depth + 1)
            return
        for name, child in (node.get("properties") or {}).items():
            names.add(name)
            walk(child, depth + 1)
        if "items" in node:
            walk(node["items"], depth + 1)

    walk(schema)
    return names


@pytest.mark.parametrize("screen", sorted(SCREEN_READS))
def test_the_operation_a_screen_would_call_exists(screen: str) -> None:
    """A named operation that does not exist is a citation pointing at nothing.

    Separate from the field check below so the failure says *which* problem it is: an operation
    renamed since this file was written reads very differently from a field that was never added.
    """

    spec = contract()
    operation_id = SCREEN_READS[screen]["operation"]
    assert _operation(spec, operation_id) is not None, (
        f"{screen}: the contract has no operation {operation_id!r}. Either it was renamed, or "
        "this entry names a read that was never built."
    )


@pytest.mark.parametrize("screen", sorted(SCREEN_READS))
def test_a_specified_screen_can_be_fed_by_the_contract(screen: str) -> None:
    """UI-READ-001. Every field §21 requires is in the response the screen would bind to.

    The failure names the missing fields, because "this screen is not ready" is not actionable at
    the moment somebody is about to estimate seven slices against it.
    """

    spec = contract()
    entry = SCREEN_READS[screen]
    operation = _operation(spec, entry["operation"])
    assert operation is not None, f"{screen}: no operation {entry['operation']!r}"

    available = _response_properties(spec, operation)
    missing = sorted(entry["requires"] - available)

    assert missing == [], (
        f"{screen} needs fields the contract does not return: {missing}\n"
        f"Operation {entry['operation']!r} returns: {sorted(available)}\n"
        "Per the screens plan §1.4, this is a finding for a backend slice rather than something "
        "the frontend can work around."
    )


def test_the_survey_covers_more_than_one_screen() -> None:
    """Guard the guard. A survey of one screen passes and proves nothing about the phase.

    This is deliberately weak — it grows as slices 1 to 7 add the screens they are about, and its
    job is only to refuse a file that has quietly stopped surveying.
    """

    assert len(SCREEN_READS) >= 2, "the survey has shrunk to something that cannot find anything"
