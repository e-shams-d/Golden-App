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
