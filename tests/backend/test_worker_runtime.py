"""The worker process must build its own resources, and only after the fork.

`RuntimeServices.from_settings` is called by the FastAPI lifespan and nowhere
else, so a Celery task has no engine and no session factory. These tests pin the
wiring that fixes that, and the two ways it can be got wrong.

A pool created before Celery forks is inherited by every child, and the children
then share sockets they each believe they own. The resulting errors look like
random corruption and are very hard to trace back to the import that caused them
— so construction is on the `worker_process_init` signal, and nothing in the
module runs at import.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from app.workers import runtime as worker_runtime_module


class FakeRuntime:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def clean_process_state() -> Iterator[None]:
    worker_runtime_module.reset_worker_runtime()
    yield
    worker_runtime_module.reset_worker_runtime()


def test_a_task_before_configuration_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lazily constructing here would create one pool per fork, owned by nobody.

    The error names the wiring, because the symptom otherwise appears far away
    from the cause.
    """

    with pytest.raises(RuntimeError, match="worker_process_init"):
        worker_runtime_module.worker_runtime()


def test_configuration_is_idempotent_within_a_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Celery can emit the signal more than once; a second engine would leak the first."""

    built: list[FakeRuntime] = []

    def build(_settings: Any) -> FakeRuntime:
        instance = FakeRuntime()
        built.append(instance)
        return instance

    monkeypatch.setattr(
        worker_runtime_module.RuntimeServices, "from_settings", staticmethod(build)
    )

    first = worker_runtime_module.configure_worker(settings=object())
    second = worker_runtime_module.configure_worker(settings=object())

    assert first is second
    assert len(built) == 1, "a second call built another engine and orphaned the first"


def test_the_configured_runtime_is_what_tasks_receive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = FakeRuntime()
    monkeypatch.setattr(
        worker_runtime_module.RuntimeServices,
        "from_settings",
        staticmethod(lambda _settings: instance),
    )

    worker_runtime_module.configure_worker(settings=object())

    assert worker_runtime_module.worker_runtime() is instance


def test_shutdown_releases_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise a worker restart leaks its connections."""

    instance = FakeRuntime()
    monkeypatch.setattr(
        worker_runtime_module.RuntimeServices,
        "from_settings",
        staticmethod(lambda _settings: instance),
    )

    worker_runtime_module.configure_worker(settings=object())
    worker_runtime_module.shutdown_worker()

    assert instance.closed is True
    with pytest.raises(RuntimeError):
        worker_runtime_module.worker_runtime()


def test_shutdown_without_configuration_is_harmless() -> None:
    """The signal can fire on a process that never configured itself."""

    worker_runtime_module.shutdown_worker()


def test_configure_accepts_celerys_signal_arguments() -> None:
    """Connected directly to `worker_process_init`, with no adapter in between.

    A wrapper would be one more place for the wiring to be wrong, and wiring is
    the thing these tests exist to protect.
    """

    import inspect

    signature = inspect.signature(worker_runtime_module.configure_worker)
    kinds = {parameter.kind for parameter in signature.parameters.values()}

    assert inspect.Parameter.VAR_KEYWORD in kinds, (
        "configure_worker cannot absorb Celery's signal kwargs, so connecting it "
        "directly would raise at worker start"
    )


def test_nothing_is_constructed_at_import_time() -> None:
    """Import must be free of side effects; the fork happens afterwards."""

    worker_runtime_module.reset_worker_runtime()

    with pytest.raises(RuntimeError):
        worker_runtime_module.worker_runtime()
