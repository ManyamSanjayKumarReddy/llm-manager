"""API key administration (admins only)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from llm_manager.api.deps import AdminDep, ContainerDep, client_ip
from llm_manager.api.pagination import PageDep
from llm_manager.core.errors import InvalidInputError
from llm_manager.db.models import User
from llm_manager.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from llm_manager.schemas.pagination import Page
from llm_manager.services.api_keys import KeyStatus

router = APIRouter(prefix="/api/keys", tags=["api keys"])


@router.get("")
async def list_keys(
    _: AdminDep,
    container: ContainerDep,
    paging: PageDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    status_filter: Annotated[KeyStatus | None, Query(alias="status")] = None,
) -> Page[ApiKeyOut]:
    """One page of keys, newest first (never their tokens); ``q`` searches labels."""
    keys, total = await container.api_keys.page(
        q=q, status=status_filter, offset=paging.offset, limit=paging.page_size
    )
    items = [ApiKeyOut.from_key(k, k.created_by.username if k.created_by else None) for k in keys]
    return Page.of(items, total, paging.page, paging.page_size)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_key(
    body: ApiKeyCreate, request: Request, admin: AdminDep, container: ContainerDep
) -> ApiKeyCreated:
    """Create a key. The token is in this response only; it cannot be shown again."""
    unknown = [m for m in body.allowed_models or [] if m not in container.manager.models]
    if unknown:
        raise InvalidInputError(f"unknown model(s): {', '.join(unknown)}")
    creator = await User.get(id=admin.user_id)
    key, token = await container.api_keys.create(
        body.label,
        created_by=creator,
        allowed_models=body.allowed_models,
        rpm_limit=body.rpm_limit,
        actor=admin.username,
        ip=client_ip(request, container),
    )
    return ApiKeyCreated(**ApiKeyOut.from_key(key, admin.username).model_dump(), token=token)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: UUID, request: Request, admin: AdminDep, container: ContainerDep
) -> None:
    """Revoke a key; it stops working immediately."""
    await container.api_keys.revoke(key_id, actor=admin.username, ip=client_ip(request, container))
