"""Control 1: the attempt read stops setting an ETag.

The route still answers 200 and `record_version` is still in the body, so **nothing about the
response looks wrong** — a client just has no server-issued precondition to echo, and the only
remaining option is to build `"rv-${record_version}"` itself. That value is present, well-formed
and meaningless, which is the worst of the three available states.

This is the defect the slice existed to fix, so the control removes the fix rather than breaking
the route: a 500 would be caught by anything.
"""

import pathlib

ROUTER = pathlib.Path("services/backend/app/api/v1/payment_attempts.py")

BEFORE = '    response.headers["ETag"] = f\'"rv-{rendered.record_version}"\'\n    return rendered\n'
AFTER = "    return rendered\n"

text = ROUTER.read_text(encoding="utf-8")
assert BEFORE in text, "the read no longer sets the ETag this way; this control does not apply"

ROUTER.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = ROUTER.read_text(encoding="utf-8")
assert 'response.headers["ETag"]' not in after, "THE EDIT DID NOT LAND"
print("control 1 applied: the attempt read issues no ETag")
