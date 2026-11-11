"""Persists request records and router events without ever slowing a request down."""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from tortoise.exceptions import BaseORMException

from llm_manager.db.models import Event, RequestLog
from llm_manager.schemas.status import EventOut

log = logging.getLogger(__name__)

_QUEUE_SIZE = 10_000
_BATCH_SIZE = 200


@dataclass(frozen=True)
class RequestRecord:
    """One finished proxied request (no prompt or response content)."""

    model: str
    api_key_id: UUID | None
    status: int
    duration_ms: int
    queue_wait_ms: int


class Recorder:
    """Queues records in memory and writes them to the database in batches.

    The queue is bounded: if the database is slow or down, records are dropped
    (and counted) rather than blocking inference.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[RequestRecord | EventOut] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self.dropped = 0

    def record_request(self, record: RequestRecord) -> None:
        """Queue a request record. Never blocks."""
        self._put(record)

    def record_event(self, event: EventOut) -> None:
        """Queue a router event. Never blocks."""
        self._put(event)

    def _put(self, item: RequestRecord | EventOut) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self.dropped += 1

    async def run(self) -> None:
        """Write queued records until cancelled; flush what is left on the way out."""
        try:
            while True:
                batch = [await self._queue.get()]
                while len(batch) < _BATCH_SIZE and not self._queue.empty():
                    batch.append(self._queue.get_nowait())
                await self._write(batch)
        finally:
            leftovers: list[RequestRecord | EventOut] = []
            while not self._queue.empty():
                leftovers.append(self._queue.get_nowait())
            if leftovers:
                with contextlib.suppress(asyncio.CancelledError):
                    await self._write(leftovers)

    @staticmethod
    async def _write(batch: list[RequestRecord | EventOut]) -> None:
        requests = [
            RequestLog(
                model=r.model,
                api_key_id=r.api_key_id,
                status=r.status,
                duration_ms=r.duration_ms,
                queue_wait_ms=r.queue_wait_ms,
            )
            for r in batch
            if isinstance(r, RequestRecord)
        ]
        events = [
            Event(ts=datetime.fromtimestamp(e.t, UTC), model=e.model, kind=e.kind, detail=e.detail)
            for e in batch
            if isinstance(e, EventOut)
        ]
        try:
            if requests:
                await RequestLog.bulk_create(requests)
            if events:
                await Event.bulk_create(events)
        except BaseORMException:
            log.exception("could not persist %d records", len(batch))
