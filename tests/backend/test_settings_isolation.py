"""The ambient environment must stay invisible to these tests.

Settings declares every field with a `validation_alias`, `populate_by_name`, and
`extra="forbid"`. That combination has a trap: when the alias is present in the
environment, the environment source fills the field through the alias, the value
supplied by field name is left unconsumed, and pydantic reports the field name
as an extra input. The message names a field the model plainly declares, which
sends the reader looking in the wrong place entirely.

An exported DATABASE_URL is an ordinary thing for a developer to have, and the
CI job that provisions PostgreSQL exports these too, so the isolation fixture in
conftest is load-bearing. These tests keep it that way.
"""

from __future__ import annotations

import os

import pytest
from app.core.config import Settings
from pydantic import ValidationError
from settings_environment import settings_environment_names


def test_introspection_finds_the_aliases_it_is_meant_to_hide() -> None:
    names = settings_environment_names()

    # Spot-check the two that actually bite, and guard against a refactor that
    # leaves the derivation returning an empty or near-empty set, which would
    # disable the isolation without failing anything else.
    assert "DATABASE_URL" in names
    assert "REDIS_URL" in names
    assert len(names) >= len(Settings.model_fields)


def test_no_settings_variable_is_visible_while_a_test_runs() -> None:
    leaked = sorted(name for name in os.environ if name.upper() in settings_environment_names())

    assert leaked == [], (
        f"{leaked} reached a test from the surrounding environment. Results would "
        "depend on the machine, and an exported alias makes Settings reject the "
        "matching field as an extra input."
    )


def test_an_exported_alias_makes_a_by_name_value_look_like_an_extra_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the pydantic behaviour the isolation exists to work around.

    If a future pydantic release stops treating the leftover by-name key as
    extra, this test fails and the fixture can be reconsidered rather than kept
    forever for a reason nobody remembers.
    """

    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    with pytest.raises(ValidationError) as raised:
        Settings(
            _env_file=None,
            app_env="test",
            database_url="postgresql+psycopg://app:secret@127.0.0.1/test",
            redis_url="redis://:other-secret@127.0.0.1:6379/0",
            local_storage_root="/tmp/does-not-need-to-exist",
        )

    errors = raised.value.errors()
    assert any(
        error["type"] == "extra_forbidden" and error["loc"] == ("redis_url",) for error in errors
    ), errors
