"""Durable idempotency with exactly one logical execution per key.

Three branches, and which one applies is decided by the database, not by a
prior read:

1. Same key, same request hash, already completed → return the stored response
   without re-executing.
2. Same key, different request hash → 409. The caller reused a key for different
   content, and returning the first response for the second request would be a
   silent wrong answer.
3. No record yet → this call executes.

The claim is made by **inserting first and catching the unique violation**, never
by SELECT-then-INSERT. Under READ COMMITTED two concurrent requests both see no
row, both decide to execute, and both run the command — the exact duplicate the
key exists to prevent. Only the unique index can decide, and only if the insert
is the thing that asks it.

The insert therefore runs inside a savepoint. Without one, the losing request's
unique violation would abort the whole transaction, so the loser could not go on
to read the winner's record and return its response — nor write audit about
having been deduplicated.

Completion is written inside the business transaction. Committing it beforehand
would leave a record claiming success for work that had not happened yet, and any
crash in between would make the command permanently unrepeatable.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import IdempotencyKeyReusedError
from app.core.time import utc_now
from app.db.models.idempotency_record import IdempotencyRecord
from app.db.unit_of_work import SqlAlchemyUnitOfWork

STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

DEFAULT_RETENTION = timedelta(hours=24)


def request_hash(payload: dict[str, Any]) -> str:
    """A digest of the request, stable under key order and formatting.

    `sort_keys` and a fixed separator matter: without them the same request
    serialised twice can hash differently, and branch 2 would reject a legitimate
    retry as a key reuse.
    """

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def key_hash(idempotency_key: str) -> str:
    """What audit is allowed to store. The raw key is a bearer value."""

    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IdempotencyClaim:
    """The outcome of asking for the right to execute."""

    record: IdempotencyRecord
    is_replay: bool

    @property
    def should_execute(self) -> bool:
        return not self.is_replay


class IdempotencyResolver:
    """Claims the right to execute, or hands back what the first attempt returned."""

    def __init__(self, uow: SqlAlchemyUnitOfWork, *, retention: timedelta = DEFAULT_RETENTION):
        self._uow = uow
        self._retention = retention

    def claim(
        self,
        *,
        actor_type: str,
        actor_id: uuid.UUID,
        operation: str,
        idempotency_key: str,
        payload: dict[str, Any],
        now: datetime | None = None,
    ) -> IdempotencyClaim:
        moment = now or utc_now()
        digest = request_hash(payload)

        record = IdempotencyRecord(
            actor_type=actor_type,
            actor_id=actor_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=digest,
            status=STATUS_IN_PROGRESS,
            expires_at=moment + self._retention,
        )

        try:
            with self._uow.savepoint():
                self._uow.session.add(record)
                # Flush rather than wait for commit: the unique violation has to
                # happen now, while it can still be caught and turned into a
                # replay. At commit time there is nothing left to fall back to.
                self._uow.flush()
        except IntegrityError:
            existing = self._existing(
                actor_type=actor_type,
                actor_id=actor_id,
                operation=operation,
                idempotency_key=idempotency_key,
            )
            if existing is None:
                # The unique index refused the insert, so a row exists that this
                # transaction cannot see. Re-raising is the honest answer: the
                # caller retries and finds it. Inventing a replay here would
                # return a response that was never produced.
                raise
            return self._replay_or_conflict(existing, digest)

        return IdempotencyClaim(record=record, is_replay=False)

    def _existing(
        self, *, actor_type: str, actor_id: uuid.UUID, operation: str, idempotency_key: str
    ) -> IdempotencyRecord | None:
        return self._uow.session.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.actor_type == actor_type,
                IdempotencyRecord.actor_id == actor_id,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()

    def _replay_or_conflict(
        self, existing: IdempotencyRecord, digest: str
    ) -> IdempotencyClaim:
        if existing.request_hash != digest:
            raise IdempotencyKeyReusedError()

        # Same key, same request, but the first attempt has not finished. Treating
        # this as a replay would return a response that does not exist yet, and
        # executing again would defeat the key. The caller is told to retry.
        if existing.status != STATUS_COMPLETED:
            raise IdempotencyKeyReusedError(
                "A request with this idempotency key is still in progress. Retry shortly."
            )

        return IdempotencyClaim(record=existing, is_replay=True)

    def complete(
        self,
        claim: IdempotencyClaim,
        *,
        response_code: int,
        response_body: dict[str, Any] | None = None,
        resource_type: str | None = None,
        resource_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        """Mark the claim completed, in the command's transaction.

        `response_body` is stored and later replayed verbatim, so it must already
        be free of anything a second caller should not see. Sanitising at replay
        time would be too late — the value is durable by then.
        """

        record = claim.record
        record.status = STATUS_COMPLETED
        record.response_code = response_code
        record.response_body = response_body
        record.resource_type = resource_type
        record.resource_id = resource_id
        record.completed_at = now or utc_now()
