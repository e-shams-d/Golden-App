"""FILE-META-001: a raw storage key or path never appears in a client contract.

There are no file routes yet, so this test passes trivially today. That is exactly
when it is worth writing. The obligation is on whoever adds the first upload
endpoint in M4, and by then the reason will be a paragraph in a document nobody
opens; a failing test at the moment the field is added is a reason that arrives on
time.

Three things would each be a leak, and they leak in different directions:

  - **A `storage_key` field in a response schema.** The direct case. A client that
    knows the key can guess neighbouring keys, and any signed-URL scheme built later
    inherits a namespace the client already maps.
  - **A filesystem path in a schema.** `local_storage_root` is deployment
    information; publishing it tells an attacker the shape of the host.
  - **A `storage_key` field in a *request* schema.** The dangerous one, and the one
    that looks helpful: a client-supplied key is a path-traversal and
    overwrite-another-tenant's-file primitive at once. `storage_key` is
    server-generated, so no request body has any business carrying it.

Asserted against the generated OpenAPI document rather than against route source,
because the document is what the client package is generated from and therefore what
a frontend can actually reach.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from app.storage.keys import generate_storage_key

A_FIXED_MOMENT = datetime(2026, 8, 6, tzinfo=UTC)

# `<category>/<YYYY>/<MM>/<DD>/<32 hex>`, the shape `generate_storage_key` produces.
_KEY_SHAPE = re.compile(r"[a-z][a-z0-9_]*/\d{4}/\d{2}/\d{2}/[0-9a-f]{32}")

# Names that must not appear as a property anywhere in the schema. `path` alone is
# too common a word to forbid outright — a `resource_path` on an audit row is
# legitimate — so the list is the specific spellings that would carry an address.
FORBIDDEN_PROPERTIES = frozenset(
    {
        "storage_key",
        "storagekey",
        "storage_path",
        "storage_bucket",
        "storage_root",
        "file_path",
        "filepath",
        "absolute_path",
        "local_path",
        "object_key",
    }
)


def walk_properties(node: Any, trail: str = "") -> list[str]:
    """Every property name in the document, with the path that reached it.

    Recursive over the whole document rather than over `components.schemas`, so a
    property declared inline in a response body is caught too — which is how the
    first quick endpoint tends to be written.
    """

    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                found.extend(f"{trail}.{name}" for name in value)
            found.extend(walk_properties(value, f"{trail}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(walk_properties(value, f"{trail}[{index}]"))
    return found


@pytest.fixture
def openapi_document(app_factory) -> dict[str, Any]:
    app, _runtime, _settings = app_factory()
    return app.openapi()


def test_no_schema_property_carries_a_storage_address(
    openapi_document: dict[str, Any],
) -> None:
    offenders = [
        trail
        for trail in walk_properties(openapi_document)
        if trail.rsplit(".", 1)[-1].lower() in FORBIDDEN_PROPERTIES
    ]

    assert offenders == [], (
        "the API contract exposes a storage address:\n"
        + "\n".join(offenders)
        + "\nstorage_key is server-generated and never a client contract: in a "
        "response it is an enumeration surface, and in a request it is a "
        "path-traversal primitive."
    )


def test_no_key_shaped_string_appears_anywhere_in_the_document(
    openapi_document: dict[str, Any],
) -> None:
    """Catches an address pasted into an example, a description or a default.

    A leaked example is a real leak: the client package is generated from this
    document, and examples reach documentation a client reads. Matched by shape
    rather than by value — a generated key is random, so searching for a specific one
    would prove nothing.
    """

    serialised = json.dumps(openapi_document, ensure_ascii=False)

    key_shaped = _KEY_SHAPE.findall(serialised)

    assert key_shaped == [], f"strings shaped like a storage key appear: {key_shaped}"


def test_no_deployment_path_appears_anywhere_in_the_document(
    openapi_document: dict[str, Any],
) -> None:
    """`local_storage_root` is deployment information. Publishing it describes the
    host's layout to anyone who fetches the schema."""

    serialised = json.dumps(openapi_document, ensure_ascii=False)

    for leak in ("local_storage_root", "/var/lib/golden", "/app/storage", "storage_root"):
        assert leak not in serialised, f"{leak!r} appears in the API contract"


def test_the_guard_would_notice_a_leak() -> None:
    """Guard the guard.

    Both tests above pass on a document with no file endpoints at all, which is
    today's document — so without this, they are indistinguishable from tests that
    match nothing. Run the same detectors over a document that does leak.
    """

    leaking = {
        "components": {
            "schemas": {
                "FileResponse": {
                    "properties": {
                        "id": {"type": "string"},
                        "storage_key": {
                            "type": "string",
                            "example": generate_storage_key(
                                category="bank_receipt", moment=A_FIXED_MOMENT
                            ),
                        },
                    }
                }
            }
        }
    }

    offending_properties = [
        trail
        for trail in walk_properties(leaking)
        if trail.rsplit(".", 1)[-1].lower() in FORBIDDEN_PROPERTIES
    ]

    assert offending_properties != []
    assert _KEY_SHAPE.findall(json.dumps(leaking)) != []
