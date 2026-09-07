"""Control 3: the screen re-reads the request before acting.

**The subtlest sabotage in this slice, and it produces no error ever.**

`command_catalog.yaml`'s `current_publication_identity_revalidated` exists for one situation: a
correction lands while the trader is reading. Publishing N+1 moves the request, so the version the
person was looking at is stale and their response is refused — which is the point, because they
would otherwise be agreeing to a result they never saw.

A fresh read immediately before sending makes the precondition always current. Every request
succeeds, no gate fails, and the trader silently acknowledges the corrected result.

It is also the shape of the *sibling* page, which does exactly this and is right to: on a draft the
trader is editing their own work and a 412 would be noise. Copying a correct pattern into the one
place it is wrong is how this defect arrives.
"""

import pathlib

PAGE = pathlib.Path("apps/trader-pwa/app/requests/[requestId]/result/page.tsx")

BEFORE = "                    onClick={() => act(() => acknowledgeResult(requestId, phase.ifMatch))}\n"
AFTER = (
    "                    onClick={() =>\n"
    "                      act(async () => {\n"
    "                        const fresh = await readRequest(requestId);\n"
    "                        return acknowledgeResult(requestId, fresh.ifMatch);\n"
    "                      })\n"
    "                    }\n"
)

text = PAGE.read_text(encoding="utf-8")
assert BEFORE in text, "the acknowledge handler is no longer written this way"

PAGE.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = PAGE.read_text(encoding="utf-8")
assert "const fresh = await readRequest(requestId);" in after, "THE EDIT DID NOT LAND"
print("control 3 applied: the screen refreshes its own precondition")
