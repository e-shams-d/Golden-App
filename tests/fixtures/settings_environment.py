"""Which environment variables Settings reads, derived from Settings itself.

Kept in a module of its own rather than in conftest. pytest puts every test
directory on sys.path without packaging them, so `import conftest` resolves to
whichever conftest.py that search finds first — with tests/backend and
tests/integration both collected, that is the wrong one, and the failure is an
ImportError naming a file the reader was not thinking about.

It lives in `tests/fixtures` because both suites need it. It used to live in
`tests/backend`, which left the integration suite's isolation reachable only when
the unit suite happened to be collected in the same run — and that accident is
what hid the defect this module now serves both suites to prevent.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from app.core.config import Settings
from pydantic import AliasChoices


def settings_environment_names() -> frozenset[str]:
    """Every environment variable Settings will read.

    Derived by introspection rather than listed, so a field added later cannot
    quietly fall outside the isolation that depends on this.
    """

    names: set[str] = set()
    for field_name, field in Settings.model_fields.items():
        alias = field.validation_alias
        if isinstance(alias, str):
            names.add(alias)
        elif isinstance(alias, AliasChoices):
            names.update(choice for choice in alias.choices if isinstance(choice, str))
        else:
            names.add(field_name)
    return frozenset(name.upper() for name in names)


@contextmanager
def environment_without_settings_variables() -> Iterator[None]:
    """Remove every variable Settings reads, and put them back afterwards.

    A context manager rather than a fixture so both suites can install it at session
    scope. `pytest.MonkeyPatch.context()` is used instead of the `monkeypatch`
    fixture because that fixture is function-scoped, and a function-scoped isolation
    is precisely what failed: pytest sets higher scopes up first, so a module- or
    session-scoped fixture is built before it and sees the unmodified environment.
    """

    watched = settings_environment_names()
    with pytest.MonkeyPatch.context() as patch:
        for name in list(os.environ):
            if name.upper() in watched:
                patch.delenv(name, raising=False)
        yield
