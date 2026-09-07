"""Control 2: the trader screen invents a current dispatch.

`gold_dispatches` carries `superseded` and `cancelled` among its six statuses and has no unique
constraint per order, so "the current dispatch" is a concept this system does not define. A screen
naming one has promoted a guess to a variable — and the guess is wrong the first time a dispatch is
superseded, at which point the trader acknowledges a movement that was replaced.

Written as the tidy-looking refactor: name the thing the screen is obviously about.
"""

import pathlib

PAGE = pathlib.Path("apps/trader-pwa/app/gold-orders/[orderId]/page.tsx")

BEFORE = '    const pending = phase.dispatches.find((row) => row.status === "dispatched");\n'
AFTER = "    const current_dispatch = phase.dispatches[phase.dispatches.length - 1];\n    const pending = current_dispatch;\n"

text = PAGE.read_text(encoding="utf-8")
assert BEFORE in text, "the pending lookup is no longer written this way"

PAGE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PAGE.read_text(encoding="utf-8")
assert "current_dispatch" in after, "THE EDIT DID NOT LAND"
print("control 2 applied: the screen names a current dispatch")
