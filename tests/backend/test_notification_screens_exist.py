"""The notification screens exist, are reachable, and are swept.

M11 Screens slice 1.

**This file exists because the traceability scanner reads `tests/` at the repository root and
nothing else**, so an obligation discharged only by a vitest suite would look uncovered.
`tests/backend/test_approval_screens_exist.py` set the precedent in M7 and states the reasoning at
length; this is the same shape for the same reason.

What a Python test can honestly check here is structural: the pages are there, both applications
have their own data module rather than sharing one, the routes are in the accessibility sweep, and
the navigation item carries no permission. The behaviour — loading, marking read, the count — is in
`apps/*/test/` and runs under `pnpm check`.

Covers: UI-NOTIFY-001.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APPS = REPOSITORY_ROOT / "apps"
ADMIN = APPS / "admin-web"
TRADER = APPS / "trader-pwa"

PAGES = {
    "admin-web": ADMIN / "app" / "notifications" / "page.tsx",
    "trader-pwa": TRADER / "app" / "notifications" / "page.tsx",
}
MODULES = {
    "admin-web": ADMIN / "src" / "notifications.ts",
    "trader-pwa": TRADER / "src" / "notifications.ts",
}
SWEEPS = {
    "admin-web": ADMIN / "tests" / "a11y" / "shell.spec.ts",
    "trader-pwa": TRADER / "tests" / "a11y" / "shell.spec.ts",
}
NAVIGATION = {
    "admin-web": ADMIN / "src" / "navigation.ts",
    "trader-pwa": TRADER / "src" / "navigation.ts",
}


@pytest.mark.parametrize("app", sorted(PAGES))
def test_each_application_has_its_own_notifications_page(app: str) -> None:
    """Both audiences, and the table M9 built is finally rendered by something."""

    assert PAGES[app].is_file(), f"{app} has no notifications page"


@pytest.mark.parametrize("app", sorted(MODULES))
def test_each_application_has_its_own_data_module(app: str) -> None:
    """`UI-ISO-001`: neither bundle may contain the other's endpoint paths.

    Notifications are the first surface where **both audiences call one route**, which is exactly
    when a shared module looks obviously right — and exactly the case the rule exists for. A shared
    module is one import away from carrying the other side's paths the first time somebody adds a
    helper to it.
    """

    assert MODULES[app].is_file(), f"{app} has no notifications data module"


@pytest.mark.parametrize("app", sorted(SWEEPS))
def test_the_notifications_route_is_in_the_accessibility_sweep(app: str) -> None:
    """`TRACE-SCREENS-001`'s rule: the sweep lists what a person can open.

    That obligation was written as "compare the sweep against the routes that exist" rather than
    "the screens this plan adds", which is the only reason it caught `/login` being unswept since
    M3. A page added without an entry here fails it immediately.
    """

    assert '"/notifications"' in SWEEPS[app].read_text(encoding="utf-8"), (
        f"{app}: the notifications route is not in the accessibility sweep"
    )


@pytest.mark.parametrize("app", sorted(NAVIGATION))
def test_the_navigation_item_carries_no_permission(app: str) -> None:
    """**The one structural claim worth asserting from here**, because it looks like a mistake.

    Every other gated application in this repository names a permission on its navigation items,
    and `apps/admin-web/src/navigation.ts` opens with a long note about gating on the permission
    that lets you *act*. A reader finding `/notifications` without one would reasonably assume it
    was forgotten.

    It was not. `permission_catalog.yaml` has no notification permission at all — access is decided
    by `notifications.recipient_actor_id`, which the server takes from the session — so there is
    nothing to name, and gating on a neighbouring grant would hide a person's own messages behind
    an authority unrelated to them.

    Asserted by reading the item's own lines rather than by parsing the module, because the module
    is TypeScript and the claim is narrow: the entry exists and no `permission:` appears with it.
    """

    source = NAVIGATION[app].read_text(encoding="utf-8")
    assert '"/notifications"' in source, f"{app}: no notifications navigation item"

    start = source.index('"/notifications"')
    # The item ends at the next `}` — enough to cover both the one-line and the multi-line form
    # this repository uses, and short enough that a neighbouring item's permission cannot leak in.
    entry = source[start : source.index("}", start)]
    assert "permission" not in entry, (
        f"{app}: the notifications navigation item names a permission. The catalogue has none for "
        "notifications; if one has been added, this test should be updated deliberately rather "
        "than the gate loosened."
    )
