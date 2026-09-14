"""The production stack differs from the local one in the ways it should, and no others.

M12 slice 3. §20.4 asks for a production-like Compose stack, pinned immutable images and an Nginx
HTTPS configuration.

**A production configuration nobody runs until the day it matters is the most dangerous file in a
repository.** Nothing here can prove the deployment works — that is M13's question — but three
things can be checked without a server, and each of them was wrong in this slice's first draft:

- every image the production overlay names is pinned by **digest**, not by a tag somebody can move;
- the production nginx configuration serves the same locations and the same security headers as the
  local one, so what ships is not quietly weaker than what was tested;
- HSTS is enabled **only** where TLS exists, because `Strict-Transport-Security` on a host with no
  certificate tells every browser to refuse the only scheme that works.

## What is not checked here, and is checked elsewhere

That the configuration *parses* is `nginx -t`'s job, and it found three defects reading was never
going to: `${TRADER_HOST}` is nine literal characters in an image whose entrypoint is `[]`;
`admin-access.conf` in `conf.d/` would have applied its `allow` rules to every audience including
traders; and a production file beside `local.conf` gives nginx two definitions of every upstream.
The fix for all three is the `deployment/` directory these tests assert the shape of.

Covers: OPS-STACK-001, OPS-STACK-002.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_LOCAL = REPOSITORY_ROOT / "infra" / "compose" / "compose.local.yml"
COMPOSE_PROD = REPOSITORY_ROOT / "infra" / "compose" / "compose.prod.yml"
NGINX_LOCAL = REPOSITORY_ROOT / "infra" / "nginx" / "conf.d" / "local.conf"
NGINX_PROD = REPOSITORY_ROOT / "infra" / "nginx" / "deployment" / "production.conf"
DEPLOYMENT = REPOSITORY_ROOT / "infra" / "nginx" / "deployment"

# The security headers every server block owes. Read from the local configuration rather than
# listed here: two copies of a list disagree the day one gains a header, and neither copy says
# which is wrong — the reason `infra/verification/lint_targets.txt` exists in the shape it does.
def _headers(text: str) -> set[str]:
    return set(re.findall(r"add_header\s+([A-Za-z-]+)", text))


def test_every_production_image_is_pinned_by_digest() -> None:
    """A tag is a pointer somebody can move; a digest is the bytes.

    §20.4 says "pinned immutable images", and `16.14-alpine3.24` today need not be the same bytes
    as `16.14-alpine3.24` after a rebuild. The digests here are the ones CI's container scan
    examined, so what was scanned and what ships are the same image.
    """

    text = COMPOSE_PROD.read_text(encoding="utf-8")
    images = re.findall(r"^\s+image:\s*(\S+)", text, re.MULTILINE)

    assert images, "the production overlay pins no images at all"

    unpinned = [image for image in images if "@sha256:" not in image]
    assert unpinned == [], (
        f"these production images are named by tag rather than by digest: {unpinned}. A tag is a "
        "pointer somebody can move, and §20.4 asks for immutable images."
    )


def test_the_production_overlay_pins_every_third_party_image_the_local_stack_names() -> None:
    """The other direction, and the one that lets the first pass while covering less.

    An overlay that pinned one image and left the others on tags would satisfy the test above —
    every image it *names* is pinned — while shipping two unpinned services. So the set is compared
    against what the local stack actually pulls from a registry.
    """

    local = COMPOSE_LOCAL.read_text(encoding="utf-8")
    # `image:` in the local stack means a third-party image; the applications are `build:`.
    third_party = {
        name.split(":", 1)[0]
        for name in re.findall(r"^\s+image:\s*(\S+)", local, re.MULTILINE)
    }
    production = COMPOSE_PROD.read_text(encoding="utf-8")
    pinned = {
        name.split("@", 1)[0]
        for name in re.findall(r"^\s+image:\s*(\S+)", production, re.MULTILINE)
    }

    assert third_party <= pinned, (
        f"the local stack pulls {sorted(third_party - pinned)} from a registry and the production "
        "overlay does not pin them, so those services ship from a moving tag"
    )


def _location_counts(text: str) -> dict[str, int]:
    """How many times each location path appears, **not which paths appear**.

    A set comparison was the first version and a negative control was NOT CAUGHT by it: this
    deployment has two audiences, each with its own server block, so removing `/files/` from *one*
    of them left the path present and the set unchanged. Every trader would have got a 404 for
    every receipt while the gate stayed green.
    """

    counts: dict[str, int] = {}
    for _, path in re.findall(r"location\s+(\S+\s+)?(\S+)\s*\{", text):
        counts[path] = counts.get(path, 0) + 1
    return counts


def test_the_production_nginx_serves_every_location_the_local_one_does() -> None:
    """What ships must not be narrower than what was tested.

    A production configuration missing `/files/` would serve a 404 for every receipt a trader opens,
    and the local suite — which is what every other test in this repository runs against — would
    never see it.

    **Counted per audience, not collected into a set.** See `_location_counts`.
    """

    local = _location_counts(NGINX_LOCAL.read_text(encoding="utf-8"))
    production = _location_counts(NGINX_PROD.read_text(encoding="utf-8"))

    short = {
        path: (production.get(path, 0), count)
        for path, count in local.items()
        if production.get(path, 0) < count
    }
    assert short == {}, (
        f"the production configuration serves these fewer times than the local one does "
        f"(production, local): {short}. Each audience has its own server block, so a location "
        "missing from one of them is invisible to a check that only asks whether the path exists."
    )


def test_the_production_nginx_is_not_weaker_on_headers() -> None:
    """Every security header the local configuration sets, production sets too — and one more.

    The extra is `Strict-Transport-Security`, which is the point of the file.
    """

    local = _headers(NGINX_LOCAL.read_text(encoding="utf-8"))
    production = _headers(NGINX_PROD.read_text(encoding="utf-8"))

    assert local <= production, (
        f"production omits security headers the local stack sets: {sorted(local - production)}"
    )
    assert "Strict-Transport-Security" in production, (
        "the production configuration terminates TLS and does not set HSTS, so a browser that "
        "reaches it once over http:// has no reason not to do so again"
    )


def test_hsts_is_enabled_only_where_tls_exists() -> None:
    """`SECURITY_HSTS_ENABLED` is true in the production overlay and nowhere else.

    HSTS on a stack with no certificate tells every browser to refuse the only scheme that works,
    and the failure lasts as long as the `max-age` — a year here. The local stack listens on 8080
    over HTTP, which is correct for a laptop and is why this must not leak into it.
    """

    assert 'SECURITY_HSTS_ENABLED: "true"' in COMPOSE_PROD.read_text(encoding="utf-8")
    assert "SECURITY_HSTS_ENABLED" not in COMPOSE_LOCAL.read_text(encoding="utf-8"), (
        "the local stack sets HSTS and serves plain HTTP; a browser that loaded it once would "
        "refuse to load it again"
    )


def test_the_production_nginx_terminates_tls() -> None:
    """`listen ... ssl` on every server block that serves an audience, and a certificate path."""

    text = NGINX_PROD.read_text(encoding="utf-8")

    assert "ssl_certificate" in text and "ssl_certificate_key" in text
    assert "listen 8443 ssl" in text
    # TLS 1.0 and 1.1 are not merely old; they are refused by every current browser, so naming them
    # would be configuring something nothing uses while implying it is supported.
    assert "ssl_protocols       TLSv1.2 TLSv1.3;" in text

    plain = [line for line in text.splitlines() if re.match(r"\s*listen\s+\d+\s*;", line)]
    assert plain == [], (
        f"the production configuration has a plaintext listener: {plain}. A redirect from http:// "
        "is interceptable by anyone on the path; with HSTS set, a connection refusal is the better "
        "first visit."
    )


def test_the_deployment_directory_holds_one_decision_per_file() -> None:
    """The three per-deployment choices, each alone in a file.

    **This shape is the fix for a real defect.** `admin-access.conf` first lived in `conf.d/`, which
    `infra/nginx/nginx.conf` includes automatically at `http` level — its `allow` rules would have
    applied to the trader application as well, locking out every trader the moment somebody
    restricted the admin panel. Here each file is included by name, from inside the one block that
    should have it.
    """

    present = {path.name for path in DEPLOYMENT.glob("*.conf")}

    assert present == {
        "production.conf",
        "admin-access.conf",
        "trader-host.conf",
        "admin-host.conf",
    }, f"unexpected files in the deployment directory: {sorted(present)}"

    # And none of them is in `conf.d/`, where the wildcard include would sweep them up.
    swept = {
        path.name for path in (REPOSITORY_ROOT / "infra" / "nginx" / "conf.d").glob("*.conf")
    }
    assert swept == {"local.conf"}, (
        f"conf.d holds {sorted(swept)}; anything here is included at http level, where a "
        "`server_name` is a syntax error and an `allow` rule applies to every audience"
    )


def test_the_admin_access_rule_is_applied_to_the_admin_block_alone() -> None:
    """OPS-004's answer must not reach the trader application.

    A rule applied to both would lock out every trader the moment the panel is restricted, which is
    the single most likely way this deployment breaks for its actual users.
    """

    text = NGINX_PROD.read_text(encoding="utf-8")
    blocks = text.split("server {")

    including = [block for block in blocks if "deployment/admin-access.conf" in block]
    assert len(including) == 1, (
        f"{len(including)} server blocks include the admin access rule; exactly one should"
    )
    assert "deployment/admin-host.conf" in including[0], (
        "the block including the admin access rule is not the admin block"
    )


def test_the_admin_access_file_says_what_the_current_state_costs() -> None:
    """OPS-004 is open, and the file that answers it must say so where somebody reads it.

    `an-exemption-must-name-its-mechanism`: "allow all" with no comment is indistinguishable from
    nobody having considered it. The M12 exit gate is blocked on this decision, and the file is
    where a person meets it.
    """

    text = DEPLOYMENT.joinpath("admin-access.conf").read_text(encoding="utf-8")

    assert "allow all;" in text, "the current state is not what this file says it is"
    assert "OPS-004" in text, "the file does not name the decision it is the answer to"
    # The consequence, not just the fact. A reader deciding whether to restrict it needs to know
    # what is true today.
    assert "username and a password" in text, (
        "the file does not say what the current state costs, which is the only thing that makes "
        "'allow all' a decision rather than a default"
    )
