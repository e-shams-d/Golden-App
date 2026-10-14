"""A timestamp the API accepts must name an instant. F-39.

ADR-006 point 2: "API timestamp values are ISO 8601 UTC values." Nothing held a request to it.
Every request field typed `datetime` accepted `2026-10-14T10:30` — exactly what a browser's
`<input type="datetime-local">` submits — and PostgreSQL, whose session zone here is UTC, stored
it as 10:30 UTC. The administrator confirming a payment types the time printed on the bank's
receipt, which is Tehran's, so every manual confirmation recorded the bank's result three and a
half hours late. Measured, not inferred: 10:30 typed, 14:00 Tehran stored.

The sweep reads every request body and query parameter the application serves, through the same
route reader the permission gates use, and decides what is a timestamp by *behaviour* — a field
that reads a zoned ISO string as a `datetime` — rather than by name or annotation. It names no
field, so a field added tomorrow is judged by the same assertion.
"""

from __future__ import annotations

import typing
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

ZONED = "2026-10-14T07:00:00Z"
# What `<input type="datetime-local">` submits.
ZONELESS = "2026-10-14T10:30"


def _models_in(annotation: Any) -> list[type[BaseModel]]:
    """The models an annotation can hold: itself, an optional one, a list of them."""

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [model for argument in typing.get_args(annotation) for model in _models_in(argument)]


def _reads_a_timestamp(annotation: Any) -> bool:
    try:
        value = TypeAdapter(annotation).validate_python(ZONED)
    except (ValidationError, TypeError):
        return False
    return isinstance(value, datetime)


def request_timestamps(app: Any) -> dict[str, Any]:
    """Every timestamp a request can carry, named `Model.field` or `METHOD path ?parameter`."""

    from fastapi.dependencies.utils import get_flat_dependant
    from fastapi.routing import APIRoute
    from test_permission_guards import routes_of

    found: dict[str, Any] = {}
    seen: set[type[BaseModel]] = set()

    def walk(model: type[BaseModel]) -> None:
        if model in seen:
            return
        seen.add(model)
        for name, field in model.model_fields.items():
            if _reads_a_timestamp(field.annotation):
                found[f"{model.__name__}.{name}"] = field.annotation
            for nested in _models_in(field.annotation):
                walk(nested)

    for method, path, route in routes_of(app):
        # The reader also returns plain Starlette routes, which take no request model. The guard
        # test below is what proves the API routes are still being read.
        if not isinstance(route, APIRoute):
            continue
        flat = get_flat_dependant(route.dependant)
        for parameter in flat.body_params:
            for model in _models_in(parameter.field_info.annotation):
                walk(model)
        for parameter in flat.query_params:
            if _reads_a_timestamp(parameter.field_info.annotation):
                found[f"{method} {path} ?{parameter.name}"] = parameter.field_info.annotation
    return found


@pytest.fixture
def timestamps(app_factory: Any) -> dict[str, Any]:
    app, _runtime, _settings = app_factory()
    return request_timestamps(app)


def test_the_sweep_sees_the_timestamps_it_must_judge(timestamps: dict[str, Any]) -> None:
    """Guard the guard. A reader that found nothing would make the next test pass vacuously.

    By name, the five request timestamps there were when the sweep was written — among them the
    one F-39 found storing the wrong instant, and the one the export screen sends.
    """

    for known in (
        "ConfirmPaidRequest.bank_result_at",
        "MarkSentRequest.sent_at",
        "DispatchRequest.dispatched_at",
        "IncomingReceiptRequest.payment_at_normalized",
        "ManualFieldsRequest.payment_at",
    ):
        assert known in timestamps, f"the sweep does not see {known}; it saw {sorted(timestamps)}"


def test_no_request_timestamp_accepts_a_value_that_names_no_instant(
    timestamps: dict[str, Any],
) -> None:
    accepting = []
    for name, annotation in timestamps.items():
        try:
            TypeAdapter(annotation).validate_python(ZONELESS)
        except ValidationError:
            continue
        accepting.append(name)

    assert accepting == [], (
        f"these accept {ZONELESS!r}, which names no instant: {accepting}. PostgreSQL reads such a "
        "value in its session zone, UTC, so a Tehran wall clock is stored three and a half hours "
        "late. Type the field `AwareDatetime`; the interface converts a typed wall clock with "
        "`tehranWallClockToInstant` from `@gold/localization`."
    )


def test_a_zoned_value_is_accepted_and_kept_as_the_same_instant() -> None:
    """The accept case. A rule that refused every timestamp would pass the test above."""

    from app.api.v1.payment_attempts import ConfirmPaidRequest

    body = ConfirmPaidRequest.model_validate(
        {"bank_tracking_number": "TRK-1", "bank_result_at": "2026-10-14T10:30:00+03:30"}
    )

    assert body.bank_result_at == datetime(2026, 10, 14, 7, 0, tzinfo=UTC)
