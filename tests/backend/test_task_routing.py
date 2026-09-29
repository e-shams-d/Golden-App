"""Every queue prefix has a module, and the routing actually matches it.

The failure this prevents is silent. `task_default_queue` is `maintenance`, so a
task whose dotted path matches no route does not error — it runs, on a queue
sized for sweeps, and the only symptom is that the queue it was meant for stays
empty.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from app.workers.celery_app import create_celery_app
from app.workers.tasks import QUEUE_MODULES

TASKS_DIR = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "backend"
    / "app"
    / "workers"
    / "tasks"
)


def test_the_configured_queues_and_the_task_modules_agree(settings_factory) -> None:
    """One source of truth, checked against the other.

    `celery_queues` in Settings and the module list here are written separately,
    so they can drift; drifting means a queue with no module, or a module routing
    to a queue no worker consumes.
    """

    settings = settings_factory()

    assert set(settings.queue_names) == set(QUEUE_MODULES)


@pytest.mark.parametrize("name", QUEUE_MODULES)
def test_every_queue_has_a_module(name: str) -> None:
    assert (TASKS_DIR / f"{name}.py").exists(), (
        f"no module for the {name!r} queue, so a task written for it would match "
        "no route and land on maintenance"
    )
    importlib.import_module(f"app.workers.tasks.{name}")


@pytest.mark.parametrize("name", QUEUE_MODULES)
def test_each_module_routes_to_its_own_queue(settings_factory, name: str) -> None:
    """Resolved through Celery's own router, not by reading the dict.

    Asserting the configuration would only prove the glob was typed; asking Celery
    proves it matches.
    """

    celery = create_celery_app(settings_factory())

    route = celery.conf.task_routes[f"app.workers.tasks.{name}.*"]

    assert route == {"queue": name}


def test_a_task_outside_the_prefixes_falls_through_to_maintenance(
    settings_factory,
) -> None:
    """Pinned because it is the failure mode, not because it is desirable.

    If this ever changes to an error, the guard above becomes unnecessary — and
    that would be an improvement worth noticing rather than a break.
    """

    celery = create_celery_app(settings_factory())

    assert celery.conf.task_default_queue == "maintenance"
    assert "app.workers.tasks.somewhere_else.*" not in celery.conf.task_routes


def test_the_ai_queue_exists_without_a_producer() -> None:
    """No Phase 1A producer, and the module still exists.

    Adding it later, after a task has already been written and deployed to the
    wrong queue, is the expensive order.
    """

    module = importlib.import_module("app.workers.tasks.ai")

    assert module.QUEUE_NAME == "ai"


def test_every_scheduled_task_is_registered(settings_factory) -> None:
    """A beat entry names its task with a string, and a string can name nothing.

    This is what F-22 was: `BEAT_SCHEDULE` named four tasks, no module was ever imported by
    the app, and the worker answered every send with
    `KeyError: 'app.workers.tasks.maintenance.poll_outbox_task'`. The outbox went unpublished
    for the platform's whole life — thirty-seven events, all `pending` — so no notification
    was ever delivered.

    Routing tests cannot see this: routing is computed from the string, and the string routes
    correctly whether or not anything answers to it.
    """

    app = create_celery_app(settings_factory())
    scheduled = {entry["task"] for entry in app.conf.beat_schedule.values()}

    missing = sorted(name for name in scheduled if name not in app.tasks)

    assert not missing, (
        "these tasks are scheduled and not registered, so the worker will raise KeyError "
        f"once per interval and the work will never run: {missing}"
    )


def test_every_task_entry_point_is_registered(settings_factory) -> None:
    """The silent half of the same failure.

    A scheduled task that is not registered at least shouts. An entry point that is not
    scheduled and not registered says nothing at all: the rows it was meant to claim stay
    queued, and the only symptom is that nothing happens. `parse_statements_task` was in that
    state — written, tested through its inner function, and unreachable.

    The task modules are read from disk rather than imported and inspected, so a module the
    app forgot to `include` is still discovered here.
    """

    app = create_celery_app(settings_factory())

    expected: set[str] = set()
    for module in sorted(TASKS_DIR.glob("*.py")):
        if module.stem == "__init__":
            continue
        for line in module.read_text(encoding="utf-8").splitlines():
            if line.startswith("def ") and line.split("(", 1)[0].endswith("_task"):
                name = line[len("def ") :].split("(", 1)[0]
                expected.add(f"app.workers.tasks.{module.stem}.{name}")

    assert expected, "no task entry points were found; this test has stopped looking"

    missing = sorted(name for name in expected if name not in app.tasks)

    assert not missing, (
        "these functions are written as Celery entry points and are not registered, so "
        f"whatever enqueues or schedules them will never be answered: {missing}"
    )
