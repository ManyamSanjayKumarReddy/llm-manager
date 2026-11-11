"""User management schemas."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import Field

from llm_manager.db.models import Role, User
from llm_manager.schemas.base import RequestSchema, ResponseSchema


class UserCreate(RequestSchema):
    """An admin creating an account."""

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    role: Role = Role.VIEWER


class UserUpdate(RequestSchema):
    """Fields an admin may change on an account."""

    is_active: bool | None = None
    role: Role | None = None


class PasswordReset(RequestSchema):
    """An admin setting a new password for someone else."""

    new_password: str = Field(min_length=1, max_length=256)


class UserOut(ResponseSchema):
    """A user, without any secret."""

    id: UUID
    username: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    locked: bool

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        """Build from an ORM user, computing whether the account is currently locked."""
        locked = user.locked_until is not None and user.locked_until > datetime.now(UTC)
        return cls(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            locked=locked,
        )
