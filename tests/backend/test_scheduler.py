"""The beat schedule, and the string coupling that makes it fragile.

Celery resolves a scheduled task by its **dotted name**. The schedule and the
function are therefore joined by a string, and renaming or moving the function
breaks the schedule silently: beat keeps firing, the worker answers "unregistered
task", and the sweep simply stops running. Nothing in the type system notices.

So these tests resolve every scheduled name to a real callable.
"""

from __future__ import annotations

import importlib
from datetime import timedelta

import pytest
from app.workers.celery_app import BEAT_SCHEDULE, create_celery_app


def test_every_scheduled_task_name_resolves_to_a_callable() -> None:
    """The check the string coupling needs.

    A rename that misses the schedule produces no error anywhere — beat fires
    into a name the worker does not know, and the only symptom is a sweep that
    quietly stopped.
    """

    for entry_name, entry in BEAT_SCHEDULE.items():
        dotted = str(entry["task"])
        module_path, _, function_name = dotted.rpartition(".")

        module = importlib.import_module(module_path)
        assert hasattr(module, function_name), (
            f"schedule entry {entry_name!r} points at {dotted!r}, which does not "
            "exist. Beat would fire into a name no worker has registered."
        )
        assert callable(getattr(module, function_name))


def test_every_scheduled_task_targets_a_configured_queue(settings_factory) -> None:
    settings = settings_factory()

    for entry_name, entry in BEAT_SCHEDULE.items():
        options = entry.get("options", {})
        assert isinstance(options, dict)
        queue = options.get("queue")
        assert queue in settings.queue_names, (
            f"{entry_name!r} targets queue {queue!r}, which no worker consumes"
        )


def test_the_schedule_reaches_the_celery_app(settings_factory) -> None:
    celery = create_celery_app(settings_factory())

    assert set(celery.conf.beat_schedule) == set(BEAT_SCHEDULE)


@pytest.mark.parametrize("entry_name", sorted(BEAT_SCHEDULE))
def test_intervals_are_recovery_paced_not_polling_paced(entry_name: str) -> None:
    """Both sweeps are safety nets, and the interval should say so.

    A dispatch registered after commit already runs immediately; the poll only
    picks up what a process death lost. Polling every second would spend a claim
    query per interval per worker to find nothing almost always.
    """

    schedule = BEAT_SCHEDULE[entry_name]["schedule"]

    assert isinstance(schedule, timedelta)
    assert schedule >= timedelta(seconds=10), (
        f"{entry_name} runs every {schedule}, which is a polling cadence for a "
        "recovery sweep"
    )


def test_the_outbox_poll_is_scheduled_at_all() -> None:
    """Guard the guard: an empty schedule would pass every check above."""

    assert BEAT_SCHEDULE, "no scheduled tasks at all"
    tasks = {str(entry["task"]) for entry in BEAT_SCHEDULE.values()}
    assert any("poll_outbox" in task for task in tasks)
    assert any("stale_lease" in task or "recover_stale" in task for task in tasks)
