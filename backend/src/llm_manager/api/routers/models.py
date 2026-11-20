"""Register and manage the vLLM containers (admins only)."""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from llm_manager.api.deps import AdminDep, ContainerDep, client_ip
from llm_manager.api.pagination import PageDep
from llm_manager.db.models import ManagedModel
from llm_manager.engine import Manager, State
from llm_manager.schemas.models import (
    ModelCheck,
    ModelCheckRequest,
    ModelCreate,
    ModelOut,
    ModelUpdate,
)
from llm_manager.schemas.pagination import Page

router = APIRouter(prefix="/api/models", tags=["models"])


def _out(row: ManagedModel, manager: Manager) -> ModelOut:
    runtime = manager.models.get(row.name)
    return ModelOut(
        name=row.name,
        server=row.server.name,
        url=row.url,
        served_name=row.served_name,
        gpus=sorted(row.gpus),
        idle_minutes=row.idle_minutes,
        priority=row.priority,
        has_api_key=bool(row.backend_api_key),
        container=row.container_name,
        created_at=row.created_at,
        state=runtime.shown_state if runtime else "unknown",
        detail=runtime.detail if runtime and runtime.state is State.DOWN else None,
        inflight=runtime.inflight if runtime else 0,
        waiting=runtime.waiting if runtime else 0,
    )


@router.get("")
async def list_models(
    _: AdminDep,
    container: ContainerDep,
    paging: PageDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> Page[ModelOut]:
    """One page of registered models with their live state."""
    rows, total = await container.models.page(q=q, offset=paging.offset, limit=paging.page_size)
    items = [_out(r, container.manager) for r in rows]
    return Page.of(items, total, paging.page, paging.page_size)


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_model(
    body: ModelCreate, request: Request, admin: AdminDep, container: ContainerDep
) -> ModelOut:
    """Start managing an existing container."""
    row = await container.models.create(
        body, actor=admin.username, ip=client_ip(request, container)
    )
    return _out(row, container.manager)


@router.post("/check")
async def check_model(body: ModelCheckRequest, _: AdminDep, container: ContainerDep) -> ModelCheck:
    """Look at a container (nothing is registered or changed)."""
    return await container.models.check(body)


@router.patch("/{name}")
async def update_model(
    name: str, body: ModelUpdate, request: Request, admin: AdminDep, container: ContainerDep
) -> ModelOut:
    """Change priority, idle time or (while the model is idle) where it runs."""
    row = await container.models.update(
        name, body, actor=admin.username, ip=client_ip(request, container)
    )
    return _out(row, container.manager)


@router.post("/{name}/sleep", status_code=status.HTTP_204_NO_CONTENT)
async def sleep_model(
    name: str, request: Request, admin: AdminDep, container: ContainerDep
) -> None:
    """Put an idle, awake model to sleep now."""
    await container.models.sleep(name, actor=admin.username, ip=client_ip(request, container))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_model(
    name: str, request: Request, admin: AdminDep, container: ContainerDep
) -> None:
    """Stop managing a model (its container keeps running, untouched)."""
    await container.models.remove(name, actor=admin.username, ip=client_ip(request, container))
