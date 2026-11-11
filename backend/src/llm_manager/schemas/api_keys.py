"""API key schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from llm_manager.db.models import ApiKey
from llm_manager.schemas.base import RequestSchema, ResponseSchema


class ApiKeyCreate(RequestSchema):
    """Create a key. Restrict it to some models and/or a requests-per-minute budget."""

    label: str = Field(min_length=1, max_length=100)
    allowed_models: list[str] | None = Field(None, description="null = all models")
    rpm_limit: int | None = Field(None, ge=1, le=100_000, description="null = unlimited")


class ApiKeyOut(ResponseSchema):
    """A key as listed: never contains the token itself."""

    id: UUID
    label: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    allowed_models: list[str] | None
    rpm_limit: int | None
    created_by: str | None

    @classmethod
    def from_key(cls, key: ApiKey, created_by: str | None) -> "ApiKeyOut":
        """Build from an ORM key and the username of its creator."""
        return cls(
            id=key.id,
            label=key.label,
            prefix=key.prefix,
            created_at=key.created_at,
            last_used_at=key.last_used_at,
            revoked_at=key.revoked_at,
            allowed_models=key.allowed_models,
            rpm_limit=key.rpm_limit,
            created_by=created_by,
        )


class ApiKeyCreated(ApiKeyOut):
    """The response to creating a key: the only time the token is ever shown."""

    token: str
