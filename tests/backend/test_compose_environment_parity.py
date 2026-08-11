"""What the backend needs to run is written down four times, so it drifted.

`app/core/config.py` declares it, `.env.example` documents it, the private `.env`
supplies it, and `infra/compose/compose.local.yml` forwards it into the container.
Nothing held those four equal, and the consequence was not cosmetic: for five
merged slices the compose stack answered **500 to every correct password** and 401
to every wrong one, because `AUTH_CSRF_KEY_SECRET` reached `.env.example` in slice
4 and reached the container never.

Two things made that invisible for so long, and both are worth naming because
either alone would have been enough:

**A wrong credential still returned 401.** Every smoke check the repository had
probed the login route with a bad password, which never reaches
`cookies.csrf_token`, so the broken path was the *success* path — the one no
negative test visits.

**The integration suite could not see it.** Each of its settings factories passes
`auth_csrf_key_secret="c" * 40` in directly
(`tests/integration/test_authentication_flow.py:74` and two others), so 514 green
integration tests and a stack that cannot log anybody in were entirely consistent
with each other. A test environment that supplies what the deployment does not is
the one gap a passing suite structurally cannot report.

The gate therefore compares the four copies rather than checking any one of them,
and it derives the list it compares from `config.py` and `.env.example` instead of
restating it — a fifth hand-written copy would be the same bug with a test beside
it.

**The criterion is not "forward everything".** Of the 38 variables `config.py`
declares, 29 are absent from compose and most should be: a statement timeout or an
Argon2 cost has a considered default, and forwarding it would move the decision
from reviewed code to an untracked file. What must be forwarded is narrower and
mechanical — a setting typed `T | None` with `default=None` is a **feature switch,
not a tunable**. Absent, the code takes a different path. `AUTH_CSRF_KEY_SECRET`
absent breaks login; `AUTH_RATE_LIMIT_KEY_SECRET` absent makes `_limiter` return
`None` (`app/api/v1/auth.py:191`), so brute-force rate limiting is simply off and
nothing says so.

Covers: OPS-ENV-001, OPS-ENV-002.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONFIG = REPOSITORY_ROOT / "services" / "backend" / "app" / "core" / "config.py"
COMPOSE = REPOSITORY_ROOT / "infra" / "compose" / "compose.local.yml"
ENV_EXAMPLE = REPOSITORY_ROOT / ".env.example"
WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "m1-verify.yml"

# One member of each derived set, asserted by name below. A count alone is a weak
# floor: a parser that starts matching the wrong thing can still return four of
# something. These say the parser is matching what it was written to match, and
# each is chosen to be the *last* thing that would ever be removed.
CANARY_OPTIONAL = "AUTH_CSRF_KEY_SECRET"
CANARY_FORWARDED = "DATABASE_URL"
CANARY_PLACEHOLDER = "POSTGRES_PASSWORD"
CANARY_GENERATED = "POSTGRES_PASSWORD"

# An optional **secret**: `SecretStr | None` with no default. The type is the
# criterion because it is the one the author already had to choose deliberately, and
# it separates the two kinds of absence cleanly. A missing secret means a control is
# off; a missing `datetime` means a fact is unknown.
#
# `default=None` is required as well as `| None`, because a setting with a real
# default is a tunable: a statement timeout or an Argon2 cost has a considered value
# in reviewed code, and forwarding it would move that decision into an untracked
# file. That is why this gate does not simply demand that all 38 declared variables
# be forwarded — 29 are absent from compose and most of them should be.
_OPTIONAL_SECRET = re.compile(
    r"^\s{4}\w+:\s*SecretStr\s*\|\s*None\s*=\s*Field\(\s*\n?\s*default=None,"
    r"\s*\n?\s*validation_alias=\"([A-Z_0-9]+)\"",
    re.MULTILINE,
)

# Any optional setting, secret or not. Used only to force a decision about new ones.
_OPTIONAL_ANY = re.compile(
    r"^\s{4}\w+:\s*[\w.]+\s*\|\s*None\s*=\s*Field\(\s*\n?\s*default=None,"
    r"\s*\n?\s*validation_alias=\"([A-Z_0-9]+)\"",
    re.MULTILINE,
)

# Optional settings that are deliberately **not** secrets, each with the reason it is
# allowed to be absent. Recorded rather than excluded by the pattern, so that adding
# a new optional non-secret setting fails this file and makes somebody write a line
# here — the alternative is a category that silently grows outside every check.
NON_SECRET_OPTIONALS: dict[str, str] = {
    "RELEASE_BUILT_AT": (
        "Build metadata, not a control. Absent it means the build time is unknown, "
        "which is a true statement about a locally built image; a default would be a "
        "false one. The release evidence records it as unfilled rather than guessing."
    ),
}

# `NAME: ${NAME:?...}` — required — versus `NAME: ${NAME:-default}` — defaulted.
_FORWARDED = re.compile(r"^\s{6}([A-Z_0-9]+):\s*(.*)$", re.MULTILINE)

_PLACEHOLDER = re.compile(r"^([A-Z_0-9]+)=((?:replace-with|change-me)\S*)$", re.MULTILINE)

# The pattern the CI generator uses to find placeholders, lifted out of the workflow
# so this file tests the real expression rather than a copy of it. Extracting it is
# the point: a copy would agree with itself while the workflow drifted.
_CI_PLACEHOLDER_PATTERN = re.compile(r'placeholder = re\.compile\(r"([^"]+)"\)')


def optional_settings() -> set[str]:
    return set(_OPTIONAL_SECRET.findall(CONFIG.read_text(encoding="utf-8")))


def all_optional_settings() -> set[str]:
    return set(_OPTIONAL_ANY.findall(CONFIG.read_text(encoding="utf-8")))


def backend_environment() -> dict[str, str]:
    """The variables the `&backend-environment` anchor sets, with their expressions.

    Read from the anchor rather than from a service, because the worker and the
    scheduler merge it too — so a variable added to one service and not the anchor
    would be forwarded to the API and silently missing from the two processes that
    run scheduled work.
    """

    text = COMPOSE.read_text(encoding="utf-8")
    _, _, after = text.partition("environment: &backend-environment")
    assert after, "the &backend-environment anchor is gone; this parser needs rewriting"
    block, _, _ = after.partition("\n    expose:")
    return dict(_FORWARDED.findall(block))


def example_placeholders() -> set[str]:
    """Variables `.env.example` ships with a value that must not be used.

    This is the honest definition of "secret" available to a test: the example file
    cannot hold real values, so the ones it deliberately spoils are exactly the ones
    a deployment has to replace.
    """

    return {name for name, _ in _PLACEHOLDER.findall(ENV_EXAMPLE.read_text(encoding="utf-8"))}


def ci_generated() -> set[str]:
    """What CI would replace, computed by running its own pattern over the example.

    The generator no longer holds a list of names — it derives them — so this applies
    the workflow's actual regex to `.env.example` and returns what it would match.
    That is a stronger question than "is the name in the list": it asks whether the
    derivation covers the file, which is the thing that failed before.
    """

    found = _CI_PLACEHOLDER_PATTERN.search(WORKFLOW.read_text(encoding="utf-8"))
    assert found, (
        "the CI .env generator's placeholder pattern was not found. Either the "
        "generator went back to a hand-written list of names — which is the drift this "
        "file exists to stop — or this parser is stale."
    )
    pattern = re.compile(found.group(1), re.MULTILINE)
    return {
        match if isinstance(match, str) else match[0]
        for match in pattern.findall(ENV_EXAMPLE.read_text(encoding="utf-8"))
    }


def test_the_parsers_are_matching_something() -> None:
    """Guard-the-guard. Every check below is a set comparison, and a set comparison
    over an empty set is the most comfortable green there is.

    A `ruff format` pass that rewrapped a `Field(...)` call, a rename of the compose
    anchor, or an edit to the workflow's generator would each leave a regex matching
    nothing — and every assertion in this file would pass. So each parser must find
    a named member that is the last thing anyone would delete.
    """

    optional = optional_settings()
    assert CANARY_OPTIONAL in optional, (
        f"the config parser did not find {CANARY_OPTIONAL}, so it is matching nothing "
        "and every parity check in this file is vacuous"
    )
    assert len(optional) >= 3, optional

    forwarded = backend_environment()
    assert CANARY_FORWARDED in forwarded, (
        f"the compose parser did not find {CANARY_FORWARDED}; the anchor's shape changed"
    )
    assert len(forwarded) >= 11, forwarded

    assert CANARY_PLACEHOLDER in example_placeholders()
    assert CANARY_GENERATED in ci_generated()


def test_every_optional_setting_is_a_gated_secret_or_a_recorded_exception() -> None:
    """A new optional setting must be classified, not inherited into the gap.

    The checks below apply to `SecretStr | None`. That is the right narrow criterion,
    and it leaves a category outside itself: an optional setting of some other type.
    Rather than let that category grow unwatched, adding one fails here until someone
    writes down why its absence is acceptable.
    """

    unclassified = sorted(all_optional_settings() - optional_settings() - set(NON_SECRET_OPTIONALS))

    assert not unclassified, (
        f"{unclassified} are optional settings that are not secrets, so nothing below "
        "checks them. Add each to NON_SECRET_OPTIONALS with the reason its absence is "
        "a true statement rather than a disabled control — or type it SecretStr."
    )

    stale = sorted(set(NON_SECRET_OPTIONALS) - all_optional_settings())
    assert not stale, (
        f"{stale} are recorded as optional non-secrets and are no longer optional "
        "settings at all; the note outlived the thing it described"
    )

    for name, reason in NON_SECRET_OPTIONALS.items():
        assert len(reason) > 60, f"{name}'s exemption needs a reason, not a placeholder"


def test_every_optional_secret_reaches_the_backend_container() -> None:
    """The defect this file exists for.

    A setting typed `T | None` with no default is a switch. If the container does not
    receive it, the deployment runs a different program from the one the tests
    exercise — and says nothing.
    """

    missing = sorted(optional_settings() - set(backend_environment()))

    assert not missing, (
        "these settings change behaviour when absent and the compose stack does not "
        f"forward them: {missing}. Each is a feature the deployment silently does not "
        "have. AUTH_CSRF_KEY_SECRET in this list is what made every correct password "
        "return 500 while every wrong one returned 401."
    )


def test_an_optional_secret_is_required_rather_than_defaulted() -> None:
    """`${NAME:?...}`, never `${NAME:-fallback}`.

    A default would let the stack start with a key the repository knows, which is
    worse than not starting: the failure moves from a message at boot to a signature
    an attacker can forge. Refusing to start is the loud version of the same fact.
    """

    forwarded = backend_environment()
    defaulted = sorted(
        name
        for name in optional_settings() & set(forwarded)
        if ":-" in forwarded[name] or ":?" not in forwarded[name]
    )

    assert not defaulted, (
        f"these secrets are forwarded with a default or unconditionally: {defaulted}. "
        "A missing secret must stop the stack, not be replaced by a value that is in "
        "the repository."
    )


def test_ci_replaces_every_placeholder_the_example_ships() -> None:
    """Present-but-published is the same defect wearing a different hat.

    The workflow used to build its `.env` by copying `.env.example` and overwriting a
    hand-written list of seven keys. Four placeholders were not on that list — both
    `AUTH_*` keys and two database roles — so they kept the example's literal text.
    Nothing fired: the variable was *set*, so `${VAR:?}` was satisfied and the stack
    started, and CI ran with credentials readable in this repository.

    The generator now derives the list, and this applies its own pattern to the
    example to check the derivation reaches every line. What this does **not** prove
    is that CI executed it — that is guaranteed instead by the generator's own
    refusal to write a file with a surviving placeholder, which fails the job rather
    than this test.
    """

    unreplaced = sorted(example_placeholders() - ci_generated())

    assert not unreplaced, (
        "the CI .env generator's pattern does not reach these placeholders in "
        f".env.example: {unreplaced}. The stack would start, so no other check fires, "
        "and the run would use a credential committed to this repository."
    )

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "placeholder values survived .env generation" in workflow, (
        "the generator's leak guard is gone. The derivation is only trustworthy "
        "because the job refuses to write a .env that still contains a spoiled value; "
        "without that, a new placeholder spelling passes silently."
    )


def test_anything_named_like_a_secret_ships_spoiled() -> None:
    """The hole the two patterns above share, closed from the other direction.

    Both the generator and `example_placeholders()` look for the *spellings*
    `replace-with` and `change-me`. A new spelling — `set-this`, `TODO`, a plausible
    dummy password — would be invisible to both, and the example would ship a value
    that reads like a real one. Neither pattern can catch that, because the vocabulary
    is what drifted.

    Names cannot drift the same way: a variable ending `_PASSWORD`, `_SECRET` or
    `_TOKEN` is a credential whatever its value looks like. So this asks the inverse
    question — is everything shaped like a secret spoiled? — and it fires on the case
    where somebody writes a convincing value instead of an obvious one.
    """

    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    spoiled = dict(_PLACEHOLDER.findall(text))
    convincing = sorted(
        name
        for name, _ in re.findall(r"^([A-Z_0-9]+)=(.*)$", text, re.MULTILINE)
        if name.endswith(("_PASSWORD", "_SECRET", "_TOKEN")) and name not in spoiled
    )

    assert not convincing, (
        f"{convincing} are named like credentials and .env.example gives them a value "
        "that is not a recognised placeholder. Either the value is real — which must "
        "never be committed — or it is a new spelling of 'replace me' that the CI "
        "generator will copy verbatim into the stack."
    )


def test_the_example_documents_every_optional_secret() -> None:
    """The last copy: a developer's private `.env` is built by hand from the example.

    It cannot be gated — it is gitignored and must be — so the example is the only
    place a gate can stand. This repository's own private `.env` was written at M1
    and never gained the twenty variables that arrived later, which is the other half
    of why the stack could not log anybody in.
    """

    documented = set(re.findall(r"^([A-Z_0-9]+)=", ENV_EXAMPLE.read_text(encoding="utf-8"), re.M))
    undocumented = sorted(optional_settings() - documented)

    assert not undocumented, (
        f"{undocumented} must be set for the stack to behave as tested, and the "
        "example a developer copies does not mention them"
    )
