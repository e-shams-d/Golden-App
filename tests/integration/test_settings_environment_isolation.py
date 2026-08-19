"""The ambient environment must stay invisible to the tests in this directory.

These tests need no database. They live here anyway, because what they describe is
a fixture in *this* directory's conftest: placed in `tests/backend` they would keep
passing while the thing they are about was gone.

The failure they exist to prevent has already happened once. The native CI job
exports `REDIS_URL` for its Redis service container. Settings declares every field
with a `validation_alias`, `populate_by_name` and `extra="forbid"`, so an exported
alias makes the environment fill the field and leaves the value passed by field
name unconsumed — reported as an extra input, naming a field the model plainly
declares. Every test here that builds an app passes `redis_url` by name.

The suite was nevertheless green for a fortnight, because the function-scoped
isolation in `tests/backend/conftest.py` was also covering this directory. That was
never load-bearing by design, and it could not cover a module-scoped fixture:
higher scopes are set up before lower ones. Five payment-request files moved their
app fixture to module scope for speed and immediately fell outside it, and CI
failed inside a fixture whose own line had not changed.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from app.core.config import Settings
from settings_environment import settings_environment_names

ADMIN_URL_VARIABLE = "INTEGRATION_ADMIN_DATABASE_URL"


@pytest.fixture(scope="module")
def names_visible_at_module_scope() -> frozenset[str]:
    """Which Settings variables the environment showed a *module*-scoped fixture.

    Module scope is the whole point of this fixture existing. A function-scoped one
    would be covered by the isolation in either conftest and would have stayed green
    through the outage this file is about.
    """

    watched = settings_environment_names()
    return frozenset(name.upper() for name in os.environ if name.upper() in watched)


@pytest.fixture(scope="module")
def settings_built_at_module_scope(tmp_path_factory: Any) -> Settings:
    """The exact construction that failed in CI, at the scope where it failed.

    Asserting on the environment alone would prove less: the trap is not that the
    variable is visible but that its visibility changes what passing a field by name
    means. So build one the way every `world` fixture here does.
    """

    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+psycopg://owner:secret@127.0.0.1:5432/itest",
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path_factory.mktemp("isolation"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="c" * 40,
        auth_rate_limit_key_secret=None,
    )


def test_no_settings_variable_is_visible_while_a_test_runs() -> None:
    leaked = sorted(name for name in os.environ if name.upper() in settings_environment_names())

    assert leaked == [], (
        f"{leaked} reached an integration test from the surrounding environment. "
        "An exported alias makes Settings reject the matching field as an extra "
        "input, so every test here that builds an app would fail naming a field the "
        "model declares."
    )


def test_no_settings_variable_is_visible_to_a_module_scoped_fixture(
    names_visible_at_module_scope: frozenset[str],
) -> None:
    """The regression. Function-scoped isolation cannot reach this far up."""

    assert names_visible_at_module_scope == frozenset(), (
        f"{sorted(names_visible_at_module_scope)} was visible while a module-scoped "
        "fixture was being built. The isolation has to be session-scoped: pytest sets "
        "higher scopes up first, so anything narrower leaves module- and "
        "session-scoped fixtures exposed."
    )


def test_settings_takes_its_values_by_name_from_a_module_scoped_fixture(
    settings_built_at_module_scope: Settings,
) -> None:
    """The failure shape itself: this construction raised ValidationError in CI."""

    assert settings_built_at_module_scope.redis_url.get_secret_value() == (
        "redis://127.0.0.1:6379/0"
    )


def test_the_admin_url_variable_survives_the_isolation() -> None:
    """It must not be swept up: without it the whole suite skips, or in CI fails.

    It is not a Settings alias, which is what keeps it safe. A field added to
    Settings under this name would silently disable the entire integration suite, so
    the guarantee is worth stating rather than assuming.
    """

    assert ADMIN_URL_VARIABLE not in settings_environment_names()


def test_the_derivation_still_finds_the_aliases_it_is_meant_to_hide() -> None:
    """A derivation that returned nothing would disable the isolation silently."""

    names = settings_environment_names()

    assert "DATABASE_URL" in names
    assert "REDIS_URL" in names
    assert len(names) >= len(Settings.model_fields)
