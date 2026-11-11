"""Historical statistics read from the database."""

from decimal import Decimal

from tortoise import Tortoise

from llm_manager.db.models import Event
from llm_manager.schemas.status import EventOut, ModelStats

_WINDOW = "ts > now() - make_interval(hours => $1)"

_PER_MODEL_SQL = f"""
SELECT model,
       COUNT(*) AS requests,
       COUNT(*) FILTER (WHERE status >= 400) AS errors,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95_ms,
       AVG(queue_wait_ms) AS avg_queue_wait_ms
FROM request_log
WHERE {_WINDOW}
GROUP BY model
ORDER BY model
LIMIT $2 OFFSET $3
"""  # noqa: S608 - the f-string only inserts a constant

_MODEL_COUNT_SQL = f"SELECT COUNT(DISTINCT model) AS n FROM request_log WHERE {_WINDOW}"  # noqa: S608


class StatsService:
    """Aggregates over the persistent request log and event history."""

    async def per_model(
        self, hours: int, *, offset: int, limit: int
    ) -> tuple[list[ModelStats], int]:
        """One page of per-model requests, errors and latency over the last ``hours``."""
        connection = Tortoise.get_connection("default")
        counted = await connection.execute_query_dict(_MODEL_COUNT_SQL, [hours])
        rows = await connection.execute_query_dict(_PER_MODEL_SQL, [hours, limit, offset])
        models = [
            ModelStats(
                model=r["model"],
                requests=int(r["requests"]),
                errors=int(r["errors"]),
                p50_ms=_round(r["p50_ms"]),
                p95_ms=_round(r["p95_ms"]),
                avg_queue_wait_ms=_round(r["avg_queue_wait_ms"]),
            )
            for r in rows
        ]
        return models, int(counted[0]["n"])

    async def events_page(
        self, *, model: str | None, kind: str | None, offset: int, limit: int
    ) -> tuple[list[EventOut], int]:
        """One page of persisted events, newest first, optionally for one model or kind."""
        query = Event.all()
        if model:
            query = query.filter(model=model)
        if kind:
            query = query.filter(kind=kind)
        total = await query.count()
        rows = await query.order_by("-id").offset(offset).limit(limit)
        return [self._event(e) for e in rows], total

    @staticmethod
    def _event(e: Event) -> EventOut:
        return EventOut(t=e.ts.timestamp(), model=e.model, kind=e.kind, detail=e.detail)

    async def recent_events(self, limit: int) -> list[EventOut]:
        """The newest persisted events (survive router restarts)."""
        events = await Event.all().order_by("-id").limit(limit)
        return [self._event(e) for e in events]


def _round(value: float | Decimal | None) -> float | None:
    return round(float(value), 1) if value is not None else None
