"""Login and session schemas."""

from pydantic import Field

from llm_manager.db.models import Role
from llm_manager.schemas.base import RequestSchema, ResponseSchema


class LoginRequest(RequestSchema):
    """Credentials submitted to the login endpoint."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SessionInfo(ResponseSchema):
    """Who is logged in. ``csrf_token`` must be sent back in the ``X-CSRF-Token`` header."""

    username: str
    role: Role
    csrf_token: str


class ChangePasswordRequest(RequestSchema):
    """A user changing their own password."""

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)
