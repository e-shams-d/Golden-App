"""Control 1: the gold order read stops issuing an ETag.

The defect that started slice 5, restored. The route still answers 200 and `record_version` is
still in the body, so nothing about the response looks wrong — four commands simply have no source
for their precondition again, and a screen's only remaining option is to compute one.
"""

import pathlib

ROUTER = pathlib.Path("services/backend/app/api/v1/gold_sale_orders.py")

BEFORE = "    response.headers[\"ETag\"] = f'\"rv-{rendered.record_version}\"'\n    return rendered\n"
AFTER = "    return rendered\n"

text = ROUTER.read_text(encoding="utf-8")
assert BEFORE in text, "the read no longer sets the ETag this way; this control does not apply"

ROUTER.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = ROUTER.read_text(encoding="utf-8")
assert 'response.headers["ETag"]' not in after, "THE EDIT DID NOT LAND"
print("control 1 applied: the gold order read issues no ETag")
