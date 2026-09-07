"""Control 2: strip the permission off a real screen.

The floor was widened from one entry to two. The question this asks is whether it is still an
equality — a check that has quietly become "at most a few are ungated" would let a genuinely
administrative screen go open and say nothing.

`/roles` is chosen deliberately: it is one of the three the frontend test names as hidden from the
operational role, so ungating it is the exact damage the floor exists to catch.
"""

import pathlib

NAVIGATION = pathlib.Path("apps/admin-web/src/navigation.ts")

BEFORE = '{ href: "/roles", label: t("admin.nav.roles"), permission: "role.read", icon: "roles" }'
AFTER = '{ href: "/roles", label: t("admin.nav.roles"), icon: "roles" }'

text = NAVIGATION.read_text(encoding="utf-8")
assert BEFORE in text, "the roles item is no longer written this way; this control does not apply"

NAVIGATION.write_text(text.replace(BEFORE, AFTER, 1), encoding="utf-8")

after = NAVIGATION.read_text(encoding="utf-8")
assert AFTER in after and BEFORE not in after, "THE EDIT DID NOT LAND"
print("control 2 applied: /roles now carries no permission")
