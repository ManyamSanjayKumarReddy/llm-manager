"""Schemas for registering and managing the vLLM containers the router controls."""

from datetime import datetime

from pydantic import Field

from llm_manager.core.models_config import (
    ApiKeyText,
    GpuSet,
    IdleMinutes,
    ModelName,
    ModelUrl,
    Priority,
)
from llm_manager.schemas.base import RequestSchema, ResponseSchema


class ModelCreate(RequestSchema):
    """An existing vLLM container to start managing."""

    name: ModelName = Field(description="what clients put in the request's 'model' field")
    url: ModelUrl
    served_name: str | None = Field(None, max_length=200, description="the name vLLM serves")
    gpus: GpuSet
    idle_minutes: IdleMinutes = 10.0
    priority: Priority = 0
    backend_api_key: ApiKeyText | None = None


class ModelUpdate(RequestSchema):
    """Fields that can change on a registered model (the name cannot)."""

    url: ModelUrl | None = None
    served_name: str | None = Field(None, max_length=200)
    gpus: GpuSet | None = None
    idle_minutes: IdleMinutes | None = None
    priority: Priority | None = None
    backend_api_key: ApiKeyText | None = None
    # Distinguish "leave as is" from "clear it": list the fields to clear.
    clear: list[str] = Field(default_factory=list, max_length=3)


class ModelOut(ResponseSchema):
    """A registered model with its live state."""

    name: str
    url: str
    served_name: str | None
    gpus: list[int]
    idle_minutes: float
    priority: int
    has_api_key: bool = Field(description="a key is stored (the key itself is never returned)")
    created_at: datetime
    state: str
    inflight: int
    waiting: int


class ModelCheckRequest(RequestSchema):
    """Where to look for a container, before registering it."""

    url: ModelUrl
    served_name: str | None = Field(None, max_length=200)
    backend_api_key: ApiKeyText | None = None


class ModelCheck(ResponseSchema):
    """What a connection test found out about a container."""

    reachable: bool
    sleep_endpoints: bool = Field(description="/is_sleeping answered (VLLM_SERVER_DEV_MODE=1)")
    state: str | None = Field(description="awake or asleep, if known")
    served_models: list[str]
    served_name_found: bool | None
    key_accepted: bool | None = Field(
        description="the container accepted (True) or refused the key"
    )
    problems: list[str]
