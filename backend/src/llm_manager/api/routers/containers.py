"""Control the vLLM containers on a server through its agent (admins only)."""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from llm_manager.api.deps import AdminDep, ContainerDep, client_ip
from llm_manager.api.pagination import PageDep
from llm_manager.schemas.containers import ContainerCreate, ContainerOut, HostOut, LogsOut
from llm_manager.schemas.pagination import Page

router = APIRouter(prefix="/api/servers/{server}", tags=["containers"])


@router.get("/host")
async def server_host(server: str, _: AdminDep, container: ContainerDep) -> HostOut:
    """GPU, memory and disk figures of the server (not stored)."""
    return await container.containers.host(server)


@router.get("/containers")
async def list_containers(
    server: str, _: AdminDep, container: ContainerDep, paging: PageDep
) -> Page[ContainerOut]:
    """One page of the containers the server's agent manages."""
    every = await container.containers.list(server)
    items = every[paging.offset : paging.offset + paging.page_size]
    return Page.of(items, len(every), paging.page, paging.page_size)


@router.post("/containers", status_code=status.HTTP_201_CREATED)
async def create_container(
    server: str, body: ContainerCreate, request: Request, admin: AdminDep, container: ContainerDep
) -> ContainerOut:
    """Create a vLLM container (and, if asked, register it as a model)."""
    return await container.containers.create(
        server, body, actor=admin.username, ip=client_ip(request, container)
    )


@router.get("/containers/{name}/logs")
async def container_logs(
    server: str,
    name: str,
    _: AdminDep,
    container: ContainerDep,
    tail: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> LogsOut:
    """The last lines the container printed."""
    return await container.containers.logs(server, name, tail)


@router.post("/containers/{name}/start")
async def start_container(
    server: str, name: str, request: Request, admin: AdminDep, container: ContainerDep
) -> ContainerOut:
    """Start a stopped container."""
    return await container.containers.start(
        server, name, actor=admin.username, ip=client_ip(request, container)
    )


@router.post("/containers/{name}/stop")
async def stop_container(
    server: str, name: str, request: Request, admin: AdminDep, container: ContainerDep
) -> ContainerOut:
    """Stop a container. Refused while the model it runs is busy."""
    return await container.containers.stop(
        server, name, actor=admin.username, ip=client_ip(request, container)
    )


@router.post("/containers/{name}/restart")
async def restart_container(
    server: str, name: str, request: Request, admin: AdminDep, container: ContainerDep
) -> ContainerOut:
    """Restart a container. Refused while the model it runs is busy."""
    return await container.containers.restart(
        server, name, actor=admin.username, ip=client_ip(request, container)
    )


@router.delete("/containers/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_container(
    server: str,
    name: str,
    request: Request,
    admin: AdminDep,
    container: ContainerDep,
    remove_model: Annotated[
        bool, Query(description="also remove the model registered for it")
    ] = False,
) -> None:
    """Delete a container. A model registered for it is only removed with ``remove_model``."""
    await container.containers.remove(
        server,
        name,
        remove_model=remove_model,
        actor=admin.username,
        ip=client_ip(request, container),
    )
