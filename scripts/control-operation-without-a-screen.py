"""Control 1: a new operation ships with no screen and no recorded reason.

**The thing this gate exists for.** A backend surface nobody can reach is the defect the whole
milestone is about — every command slices 4 to 7 built had existed for a milestone with nothing
calling it, and no gate said so.

Added to the published contract rather than to the router, because the gate reads the contract:
the sabotage has to arrive the way a real one would, which is a route that ships and a screen that
never follows.
"""

import json
import pathlib

CONTRACT = pathlib.Path("services/backend/openapi/v1.json")

contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
assert "/api/v1/unreachable-thing" not in contract["paths"], "already applied"

contract["paths"]["/api/v1/unreachable-thing"] = {
    "get": {
        "operationId": "getUnreachableThing",
        "summary": "A surface no screen reaches.",
        "responses": {"200": {"description": "OK"}},
    }
}
CONTRACT.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

after = json.loads(CONTRACT.read_text(encoding="utf-8"))
assert "/api/v1/unreachable-thing" in after["paths"], "THE EDIT DID NOT LAND"
print("control 1 applied: an operation with no screen is published")
