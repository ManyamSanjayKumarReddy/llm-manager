"""Dashboard data: live status, history and the audit trail."""

import math
from typing import Annotated

from fastapi import APIRouter, Query

from llm_manager.api.deps import AdminDep, ContainerDep, SessionDep
from llm_manager.api.pagination import PageDep
from llm_manager.schemas.pagination import Page
from llm_manager.schemas.status import AuditOut, EventOut, ModelStats, StatusOut

router = APIRouter(prefix="/api", tags=["dashboard"])

_EVENT_LIMIT = 60


@router.get("/status")
async def live_status(_: SessionDep, container: ContainerDep) -> StatusOut:
    """Live model states, GPU holders, counters and recent events."""
    snapshot = container.manager.snapshot(_EVENT_LIMIT)
    # After a restart the in-memory history is short: fill up with persisted events.
    oldest = snapshot.events[-1].t if snapshot.events else math.inf
    if len(snapshot.events) < _EVENT_LIMIT:
        older = [e for e in await container.stats.recent_events(_EVENT_LIMIT) if e.t < oldest]
        snapshot.events = (snapshot.events + older)[:_EVENT_LIMIT]
    return snapshot


@router.get("/stats")
async def history(
    _: SessionDep,
    container: ContainerDep,
    paging: PageDep,
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> Page[ModelStats]:
    """One page of requests, errors and latency per model over the last ``hours``."""
    models, total = await container.stats.per_model(
        hours, offset=paging.offset, limit=paging.page_size
    )
    return Page.of(models, total, paging.page, paging.page_size)


@router.get("/events")
async def events(
    _: SessionDep,
    container: ContainerDep,
    paging: PageDep,
    model: Annotated[str | None, Query(max_length=100)] = None,
    kind: Annotated[str | None, Query(max_length=40)] = None,
) -> Page[EventOut]:
    """One page of past wake/sleep/failure events, newest first."""
    items, total = await container.stats.events_page(
        model=model, kind=kind, offset=paging.offset, limit=paging.page_size
    )
    return Page.of(items, total, paging.page, paging.page_size)


@router.get("/audit")
async def audit_trail(
    _: AdminDep,
    container: ContainerDep,
    paging: PageDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[AuditOut]:
    """Who did what, newest first (admins only); ``q`` searches actor, action and target."""
    entries, total = await container.audit.page(q=q, offset=paging.offset, limit=paging.page_size)
    items = [AuditOut.model_validate(e) for e in entries]
    return Page.of(items, total, paging.page, paging.page_size)
