"""Control 2: the receipt read stops issuing an ETag.

The gap slice 5 recorded, restored. The route still answers 200 with `record_version` in the body,
so nothing about the response looks wrong — `confirm` simply has no source for its precondition
again and a screen's only option is to compute one.
"""

import pathlib

ROUTER = pathlib.Path("services/backend/app/api/v1/incoming_matches.py")

BEFORE = "    response.headers[\"ETag\"] = f'\"rv-{detail.record_version}\"'\n    return detail\n"
AFTER = "    return detail\n"

text = ROUTER.read_text(encoding="utf-8")
assert BEFORE in text, "the receipt read no longer sets the ETag this way"

ROUTER.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = ROUTER.read_text(encoding="utf-8")
assert "f'\"rv-{detail.record_version}\"'" not in after, "THE EDIT DID NOT LAND"
print("control 2 applied: the receipt read issues no ETag")
