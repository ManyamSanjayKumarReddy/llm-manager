"""User administration (admins only)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status

from llm_manager.api.deps import AdminDep, ContainerDep, client_ip
from llm_manager.api.pagination import PageDep
from llm_manager.db.models import Role
from llm_manager.schemas.pagination import Page
from llm_manager.schemas.users import PasswordReset, UserCreate, UserOut, UserUpdate

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
async def list_users(
    _: AdminDep,
    container: ContainerDep,
    paging: PageDep,
    q: Annotated[str | None, Query(max_length=64)] = None,
    role: Role | None = None,
) -> Page[UserOut]:
    """One page of accounts; ``q`` searches usernames."""
    users, total = await container.users.page(
        q=q, role=role, offset=paging.offset, limit=paging.page_size
    )
    return Page.of([UserOut.from_user(u) for u in users], total, paging.page, paging.page_size)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate, request: Request, admin: AdminDep, container: ContainerDep
) -> UserOut:
    """Create an account. Users cannot sign themselves up."""
    user = await container.users.create(
        body.username,
        body.password,
        body.role,
        actor=admin.username,
        ip=client_ip(request, container),
    )
    return UserOut.from_user(user)


@router.patch("/{user_id}")
async def update_user(
    user_id: UUID, body: UserUpdate, request: Request, admin: AdminDep, container: ContainerDep
) -> UserOut:
    """Enable, disable or change the role of an account."""
    if user_id == admin.user_id and (body.is_active is False or body.role is not None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "you cannot change your own access")
    user = await container.users.update(
        user_id,
        is_active=body.is_active,
        role=body.role,
        actor=admin.username,
        ip=client_ip(request, container),
    )
    return UserOut.from_user(user)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: UUID,
    body: PasswordReset,
    request: Request,
    admin: AdminDep,
    container: ContainerDep,
) -> None:
    """Set a new password for a user; they are logged out everywhere."""
    await container.users.reset_password(
        user_id, body.new_password, actor=admin.username, ip=client_ip(request, container)
    )
