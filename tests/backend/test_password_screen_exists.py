"""Changing your own password has a screen, in both applications.

M11 Screens slice 10 — the last entry slice 8's Definition of Done gate recorded as "a settings
surface no slice has owned". `POST /api/v1/auth/change-password` has existed since M3 and nothing
had ever called it: somebody signing in for the first time had no way to replace the password they
were given.

Covers: TRACE-SCREENS-002.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
APPS = ("admin-web", "trader-pwa")

_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_LINE = re.compile(r"^\s*//.*$", re.M)


def code(path: Path) -> str:
    return _LINE.sub("", _BLOCK.sub("", path.read_text(encoding="utf-8")))


def module(app: str) -> Path:
    return REPOSITORY_ROOT / "apps" / app / "src" / "password.ts"


def page(app: str) -> Path:
    return REPOSITORY_ROOT / "apps" / app / "app" / "password" / "page.tsx"


@pytest.mark.parametrize("app", APPS)
def test_each_application_has_its_own_password_surface(app: str) -> None:
    """`UI-ISO-001`: both audiences call one path, which is exactly when a shared module looks
    obviously right and is the case the rule exists for."""

    assert module(app).is_file(), f"{app} has no password module"
    assert page(app).is_file(), f"{app} has no password screen"


@pytest.mark.parametrize("app", APPS)
def test_the_screen_compares_the_two_new_password_fields(app: str) -> None:
    """**The one piece of validation this screen owns.**

    The server has no second field to compare against, so a typo in a new password is accepted and
    the person is locked out of the account they had just changed. Nothing fails: the request
    succeeds, the response says `changed: true`, and the failure arrives at the next sign-in.

    Everything else — the old password being right, the new one being acceptable — is the server's,
    and the screen reports what it says rather than predicting it.
    """

    body = code(page(app))
    assert "next !== again" in body, (
        f"{app}'s password screen does not compare the two new-password fields, so a typo locks "
        "somebody out of an account they have just changed"
    )


@pytest.mark.parametrize("app", APPS)
def test_a_wrong_current_password_is_named_as_such(app: str) -> None:
    """The route answers 403 for that specific case.

    Telling somebody their *new* password was rejected when what failed was the old one is the kind
    of message that costs a support call.
    """

    body = code(page(app))
    assert "403" in body and "password.wrongCurrent" in body, (
        f"{app}'s password screen does not distinguish a wrong current password from a rejected "
        "new one"
    )


@pytest.mark.parametrize("app", APPS)
def test_the_navigation_item_carries_no_permission(app: str) -> None:
    """**The third ungated item, and for a different reason from the second.**

    `/notifications` carries none because the catalogue holds none. `/password` carries none
    because the caller **is** the subject: the session names whose credential it is, so a grant
    would be an authority over somebody's own password. The route is guarded by the current
    password instead, which is a better check than any permission — it proves the person at the
    keyboard is the one whose credential this is.
    """

    source = (REPOSITORY_ROOT / "apps" / app / "src" / "navigation.ts").read_text(encoding="utf-8")
    assert '"/password"' in source, f"{app} has no password navigation item"

    start = source.index('"/password"')
    entry = source[start : source.index("}", start)]
    assert "permission" not in entry, (
        f"{app}: the password item names a permission. There is none to name — a grant here would "
        "be an authority over somebody's own credential."
    )


@pytest.mark.parametrize("app", APPS)
def test_the_route_is_in_the_accessibility_sweep(app: str) -> None:
    """`TRACE-SCREENS-001`: the sweep lists what a person can open."""

    swept = (
        REPOSITORY_ROOT / "apps" / app / "tests" / "a11y" / "shell.spec.ts"
    ).read_text(encoding="utf-8")
    assert '"/password"' in swept, f"{app}: the password screen is not in the accessibility sweep"
