"""Schemas for the servers (machines with GPUs) that models are placed on."""

from datetime import datetime
from typing import Annotated

from pydantic import Field

from llm_manager.core.models_config import ServerName
from llm_manager.schemas.base import RequestSchema, ResponseSchema

GpuCount = Annotated[int, Field(ge=1, le=16)]
GpuType = Annotated[str, Field(max_length=100)]


class ServerCreate(RequestSchema):
    """A machine to place models on."""

    name: ServerName = Field(description="a short label, e.g. gpu-box-2")
    gpu_count: GpuCount = Field(description="how many GPUs it has (numbered from 0)")
    gpu_type: GpuType | None = Field(
        None, description="what kind of GPUs, e.g. 2x RTX 4060 Ti 16 GB"
    )


class ServerUpdate(RequestSchema):
    """What can change on a server (the name cannot: models refer to it)."""

    gpu_count: GpuCount | None = None
    gpu_type: GpuType | None = Field(None, description="empty text clears it")


class ServerOut(ResponseSchema):
    """A server and the models placed on it."""

    name: str
    gpu_count: int
    gpu_type: str | None
    models: list[str]
    created_at: datetime
