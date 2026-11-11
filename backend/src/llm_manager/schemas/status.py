"""Dashboard schemas: live router status, history and audit trail."""

from datetime import datetime

from pydantic import Field

from llm_manager.schemas.base import ResponseSchema


class ModelStatus(ResponseSchema):
    """Live state and counters of one model (counters reset when the router restarts)."""

    state: str
    priority: int
    gpus: list[int]
    inflight: int
    waiting: int
    idle_s: float
    sleeps_after_s: float
    sleeps_in_s: float | None
    requests: int
    errors: int
    rejected: int
    wakes: int
    sleeps: int
    last_wake_s: float | None
    avg_wake_s: float | None
    waits: int
    avg_wait_s: float | None
    max_wait_s: float | None


class GpuHolder(ResponseSchema):
    """The model currently holding a GPU's memory."""

    model: str
    state: str


class EventOut(ResponseSchema):
    """A wake/sleep/failure event."""

    t: float = Field(description="unix timestamp")
    model: str | None
    kind: str
    detail: str


class StatusOut(ResponseSchema):
    """Everything the dashboard shows live."""

    uptime_s: int
    models: dict[str, ModelStatus]
    gpus: dict[str, GpuHolder | None]
    events: list[EventOut]


class ModelStats(ResponseSchema):
    """Aggregates from the persistent request log."""

    model: str
    requests: int
    errors: int
    p50_ms: float | None
    p95_ms: float | None
    avg_queue_wait_ms: float | None


class AuditOut(ResponseSchema):
    """One audit trail entry."""

    ts: datetime
    actor: str
    action: str
    target: str | None
    ip: str | None
    detail: str | None
