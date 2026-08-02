"""Which environment variables Settings reads, derived from Settings itself.

Kept in a module of its own rather than in conftest. pytest puts every test
directory on sys.path without packaging them, so `import conftest` resolves to
whichever conftest.py that search finds first — with tests/backend and
tests/integration both collected, that is the wrong one, and the failure is an
ImportError naming a file the reader was not thinking about.
"""

from __future__ import annotations

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
