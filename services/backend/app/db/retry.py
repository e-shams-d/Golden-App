"""Bounded retry for serialization failures, and a deliberate refusal to retry deadlocks.

A SERIALIZABLE transaction that loses a conflict raises 40001. That is not an
error in the work — it is the isolation level saying "run it again". Nothing here
uses SERIALIZABLE yet; the wrapper exists so the first operation that proves it
needs one does not invent its own retry loop, and so the retry boundary is a
whole transaction rather than a statement.

**Deadlocks (40P01) are deliberately not retried.** They look like the same
family of transient error and they are not. Since `app/db/locking.py` publishes
one global ordering rule, a deadlock means two code paths locked overlapping rows
in different orders — a bug in one of them. Retrying converts a reproducible
ordering defect into an intermittent slowdown that survives review, and the next
person sees a system that mostly works. Failing loudly is what gets it fixed.

The unit of retry is a callable that receives a **fresh** Unit of Work. Retrying
inside an aborted transaction is meaningless: PostgreSQL has already discarded
everything after the failure, so the second attempt must begin a new transaction
or it fails on the first statement.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.exc import DBAPIError

from app.core.errors import AppError
from app.core.logging import get_logger, log_event
from app.db.unit_of_work import SqlAlchemyUnitOfWork, UnitOfWorkFactory

SERIALIZATION_FAILURE = "40001"
DEADLOCK_DETECTED = "40P01"

logger = get_logger("db.retry")


class SerializationExhaustedError(AppError):
    """Every attempt lost its serialization conflict.

    A typed conflict rather than a bare 500: the caller's request was never
    invalid, so retrying it later is reasonable advice, and a 500 would tell them
    the opposite.
    """

    def __init__(self, attempts: int) -> None:
        super().__init__(
            "CONFLICT",
            f"The request could not be completed after {attempts} attempts due to "
            "concurrent activity. Retry shortly.",
            409,
        )


@dataclass(frozen=True)
class RetryPolicy:
    """How many times, and how long between.

    The delay grows so a burst of conflicting transactions does not resynchronise
    on the same retry instant and collide again. It stays small because these are
    request-path retries and the caller is waiting.
    """

    attempts: int = 3
    initial_delay_seconds: float = 0.02
    multiplier: float = 3.0

    def delay_before(self, attempt: int) -> float:
        return self.initial_delay_seconds * (self.multiplier ** (attempt - 1))


def sqlstate_of(error: DBAPIError) -> str | None:
    original = getattr(error, "orig", None)
    return getattr(original, "sqlstate", None)


def is_serialization_failure(error: DBAPIError) -> bool:
    return sqlstate_of(error) == SERIALIZATION_FAILURE


def is_deadlock(error: DBAPIError) -> bool:
    return sqlstate_of(error) == DEADLOCK_DETECTED


def run_with_serialization_retry[T](
    uow_factory: UnitOfWorkFactory,
    operation: Callable[[SqlAlchemyUnitOfWork], T],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run `operation` in its own transaction, retrying only on 40001.

    `operation` must not commit; this owns the transaction boundary, because that
    boundary is what is being retried.
    """

    effective = policy or RetryPolicy()
    last: DBAPIError | None = None

    for attempt in range(1, effective.attempts + 1):
        try:
            with uow_factory() as uow:
                result = operation(uow)
                uow.commit()
                return result
        except DBAPIError as error:
            if is_deadlock(error):
                # Not retried, on purpose. With one published lock ordering a
                # deadlock is an ordering violation, and retrying would turn a
                # reproducible bug into an intermittent one.
                log_event(
                    logger,
                    logging.ERROR,
                    "deadlock_not_retried",
                    sqlstate=DEADLOCK_DETECTED,
                    reason="lock ordering violation; see app/db/locking.py",
                )
                raise
            if not is_serialization_failure(error):
                raise
            last = error
            log_event(
                logger,
                logging.WARNING,
                "serialization_conflict_retrying",
                attempt=attempt,
                attempts=effective.attempts,
            )
            if attempt < effective.attempts:
                sleep(effective.delay_before(attempt))

    assert last is not None
    raise SerializationExhaustedError(effective.attempts) from last
