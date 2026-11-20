"""Register the machines with GPUs that models are placed on (admins only)."""

from fastapi import APIRouter, Request, status

from llm_manager.api.deps import AdminDep, ContainerDep, client_ip
from llm_manager.schemas.servers import ServerCreate, ServerOut, ServerUpdate, TunnelEnrolled

router = APIRouter(prefix="/api/servers", tags=["servers"])


@router.get("")
async def list_servers(_: AdminDep, container: ContainerDep) -> list[ServerOut]:
    """Every server with the models placed on it."""
    return await container.servers.list()


@router.post("", status_code=status.HTTP_201_CREATED)
async def add_server(
    body: ServerCreate, request: Request, admin: AdminDep, container: ContainerDep
) -> ServerOut:
    """Register a server."""
    return await container.servers.create(
        body, actor=admin.username, ip=client_ip(request, container)
    )


@router.patch("/{name}")
async def update_server(
    name: str, body: ServerUpdate, request: Request, admin: AdminDep, container: ContainerDep
) -> ServerOut:
    """Change how many GPUs a server has."""
    return await container.servers.update(
        name, body, actor=admin.username, ip=client_ip(request, container)
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_server(
    name: str, request: Request, admin: AdminDep, container: ContainerDep
) -> None:
    """Delete a server that has no models."""
    await container.servers.remove(name, actor=admin.username, ip=client_ip(request, container))


@router.post("/{name}/tunnel", status_code=status.HTTP_201_CREATED)
async def enroll_tunnel(
    name: str, request: Request, admin: AdminDep, container: ContainerDep
) -> TunnelEnrolled:
    """Issue the token a server's agent uses to connect out (shown once; replaces any earlier)."""
    return await container.servers.enroll_tunnel(
        name, actor=admin.username, ip=client_ip(request, container)
    )


@router.delete("/{name}/tunnel")
async def revoke_tunnel(
    name: str, request: Request, admin: AdminDep, container: ContainerDep
) -> ServerOut:
    """Stop accepting the server's agent and close its connection."""
    return await container.servers.revoke_tunnel(
        name, actor=admin.username, ip=client_ip(request, container)
    )
