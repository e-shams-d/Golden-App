"""Every authenticated page is `no-store`, and the list saying so matches the pages that exist.

M12 slice 1.

`packages/config/src/security-headers.mjs` applies `Cache-Control: no-store` to the paths each
application passes as `protectedPagePatterns`. **That list is the whole of the protection for page
routes**: `infra/nginx/conf.d/local.conf` sets `no-store, private` on `/api/` and `/files/` only,
and never on `location /`. A page absent from the list may be written to a browser's disk cache and
served from its back/forward cache — so on a shared machine, pressing Back after sign-out can
render a payment queue.

**This gate exists because the lists had gone stale in silence.** When it was written, the admin
application named nine patterns: four pointed at pages renamed during M5-M7 (`/payment-requests`
became `/requests`, `/payment-batches` became `/batches`, `/work-queues` became `/queues`), two had
never existed, and thirteen real pages were missing. The trader application listed `/results` and
`/publications`, which do not exist, while omitting `/beneficiaries` and `/evidence` — a trader's
bank details and their uploaded receipts.

Nothing in the repository compared the two. An edit would have fixed it until the next rename.

**Public pages are an explicit allowlist with a reason each.** Inferring publicness from a path —
"anything not under a dynamic segment", "anything called login" — would quietly excuse the next
page somebody forgets to list, which is exactly the failure this gate is for.

Covers: CI-CACHE-001.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# Pages a signed-out person is meant to reach. Each is named with the reason it is not protected,
# because "it does not need `no-store`" is a claim about what the page renders.
PUBLIC_PAGES: dict[str, dict[str, str]] = {
    "admin-web": {
        "login": "the sign-in form; renders nothing about anybody until it is submitted",
        "recover-password": (
            "M0 slice F. Reachable only by somebody who cannot sign in — `recovery_required` "
            "refuses authentication — so requiring a session to reach it would close the only "
            "way out of that state. It renders no account data: the 401 it reports is one answer "
            "for three causes, deliberately."
        ),
        "states": (
            "the rendered catalogue of empty/error/forbidden states, used by the accessibility "
            "sweep. Static markup with no data in it at all."
        ),
    },
    "trader-pwa": {
        "login": "the sign-in form; renders nothing about anybody until it is submitted",
        "register": "self-registration, which by definition precedes an account",
        "offline": "the service worker's fallback; it must render with no network and no session",
        "states": (
            "the rendered state catalogue, as in the admin application above: static markup used "
            "by the accessibility sweep, with no data in it"
        ),
    },
}

# Files under `app/` that are not pages. `page.tsx` is what makes a directory a page route.
#
# **`health/` is a `route.ts` in both applications and is therefore not a page at all.** It was
# briefly listed here as a public *page*, which this gate refused — correctly, and the refusal is
# worth keeping in mind: a route handler's caching is decided by the handler and by nginx, and an
# entry here would have been an exemption from a rule that never applied to it.
NOT_A_ROUTE_DIRECTORY = {"globals.css"}


def app_root(app: str) -> Path:
    return REPOSITORY_ROOT / "apps" / app / "app"


def page_directories(app: str) -> set[str]:
    """Every top-level route segment that actually renders a page.

    Read from the filesystem rather than from a list, which is the entire point: a list is what went
    stale. A directory counts when it contains a `page.tsx` at any depth, so `/batches` counts
    through `batches/[batchId]/versions/page.tsx` even if `batches/page.tsx` were removed.
    """

    root = app_root(app)
    assert root.is_dir(), f"{root} is not a directory; the app layout has moved"

    found: set[str] = set()
    for child in root.iterdir():
        if not child.is_dir() or child.name in NOT_A_ROUTE_DIRECTORY:
            continue
        if any(child.rglob("page.tsx")):
            found.add(child.name)
    return found


def protected_segments(app: str) -> set[str]:
    """The first path segment of each `protectedPagePatterns` entry."""

    config = (REPOSITORY_ROOT / "apps" / app / "next.config.ts").read_text(encoding="utf-8")
    block = re.search(r"protectedPagePatterns:\s*\[(.*?)\]", config, re.DOTALL)
    assert block is not None, f"{app} declares no protectedPagePatterns"

    segments: set[str] = set()
    for quoted in re.findall(r'"([^"]+)"', block.group(1)):
        segments.add(quoted.lstrip("/").split("/", 1)[0])
    return segments


def test_every_authenticated_page_is_listed() -> None:
    """The direction that leaks: a page exists, nothing marks it `no-store`."""

    for app, public in PUBLIC_PAGES.items():
        pages = page_directories(app)
        listed = protected_segments(app)
        unprotected = sorted(pages - listed - set(public))

        assert unprotected == [], (
            f"{app} has pages nothing marks `no-store`: {unprotected}. Add each to "
            f"`protectedPagePatterns` in apps/{app}/next.config.ts, or to `PUBLIC_PAGES` here with "
            "the reason a signed-out person may see it. nginx does not cover page routes."
        )


def test_no_pattern_points_at_a_page_that_does_not_exist() -> None:
    """The direction that hides the first one.

    A list full of stale entries looks thorough. Four of the admin application's nine patterns were
    renamed pages when this was written, and the length of the list is what made the absence of
    thirteen others unremarkable.
    """

    for app in PUBLIC_PAGES:
        pages = page_directories(app)
        stale = sorted(protected_segments(app) - pages)

        assert stale == [], (
            f"{app} protects paths with no page behind them: {stale}. A pattern for a renamed or "
            "deleted route protects nothing and makes the list look longer than its coverage."
        )


def test_no_public_page_is_recorded_that_does_not_exist() -> None:
    """The allowlist has the same failure mode as the list it excuses.

    An entry here for a page that has been deleted is an exemption nobody can evaluate — and the
    next page to take that name inherits it silently.
    """

    for app, public in PUBLIC_PAGES.items():
        missing = sorted(set(public) - page_directories(app))

        assert missing == [], (
            f"{app} records {missing} as public and no such page exists. Delete the entry: a "
            "stale exemption is inherited by whatever takes the name next."
        )


def test_every_public_page_says_why() -> None:
    """A reason, not a marker.

    `an-exemption-must-name-its-mechanism`: an exemption is only as good as the reason on it, and
    the cheapest way for this allowlist to rot is for somebody to add a name with `""` beside it.
    """

    for app, public in PUBLIC_PAGES.items():
        thin = sorted(name for name, reason in public.items() if len(reason.strip()) < 25)

        assert thin == [], (
            f"{app} excuses {thin} from `no-store` without saying what a signed-out person sees "
            "there. The reason is the exemption."
        )
