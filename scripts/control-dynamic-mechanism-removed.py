"""Control 3: the dynamic mechanism disappears while its exemption stands.

**The control that matters most in this slice.** `DYNAMIC` exempts sixteen operations — every
queue — on the strength of one sentence: the frontend builds those paths from the server's index.

If the module stops building them, sixteen surfaces become unreachable and the exemption still
reads true. "It is reached dynamically" is a sentence anybody can write about anything, which is
why the rule names the file and the gate checks it.

Modelled as the plausible refactor: rename the path so the module no longer mentions `/queues`.
"""

import pathlib

MODULE = pathlib.Path("apps/admin-web/src/queues.ts")

text = MODULE.read_text(encoding="utf-8")
assert "/queues" in text, "the module no longer mentions the queue path; control does not apply"

MODULE.write_text(text.replace("/queues", "/work-lists"), encoding="utf-8")

after = MODULE.read_text(encoding="utf-8")
assert "/queues" not in after, "THE EDIT DID NOT LAND"
print("control 3 applied: the module no longer builds queue paths")
