"""Schemas for controlling containers on a server through its agent."""

from typing import Annotated

from pydantic import Field, SecretStr

from llm_manager.core.models_config import (
    ApiKeyText,
    IdleMinutes,
    ModelName,
    ModelUrl,
    Priority,
)
from llm_manager.schemas.base import RequestSchema, ResponseSchema

ContainerName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$")]
HfModel = Annotated[
    str,
    Field(max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)?$"),
]
Token = Annotated[SecretStr, Field(max_length=512)]


class RegisterAs(RequestSchema):
    """Also register the new container as a model, so requests can reach it."""

    name: ModelName = Field(description="what clients put in the request's 'model' field")
    url: ModelUrl = Field(description="where Wakeful reaches the container")
    served_name: str | None = Field(None, max_length=200)
    idle_minutes: IdleMinutes = 10.0
    priority: Priority = 0


class ContainerCreate(RequestSchema):
    """A vLLM container to create on a server (sleep mode is always switched on)."""

    name: ContainerName
    model: HfModel
    image: Annotated[str, Field(max_length=200)]
    port: Annotated[int, Field(ge=1024, le=65535)]
    gpus: Annotated[list[int], Field(min_length=1, max_length=16)]
    cache_dir: Annotated[str, Field(max_length=300)]
    api_key: ApiKeyText | None = None
    hf_token: Token | None = None
    max_model_len: Annotated[int, Field(ge=256)] = 8192
    max_num_seqs: Annotated[int, Field(ge=1)] = 16
    memory_share: Annotated[float, Field(ge=0.1, le=0.98)] = 0.9
    allow_long_context: bool = False
    tool_calling: bool = False
    tool_parser: Annotated[str, Field(pattern=r"^[a-z0-9_]{1,40}$")] = "openai"
    auto_restart: bool = True
    extra_args: Annotated[str, Field(max_length=300)] = ""
    memory_gb: Annotated[int | None, Field(ge=1, le=2048)] = None
    cpus: Annotated[float | None, Field(gt=0, le=512)] = None
    register_as: RegisterAs | None = None


class ContainerOut(ResponseSchema):
    """A container on a server, with the model registered for it (if any)."""

    name: str
    state: str
    running: bool
    status: str
    image: str
    port: int | None
    gpus: list[int]
    model: str | None = Field(description="the Hugging Face id it was started with")
    restart_policy: str
    exit_code: int | None
    oom_killed: bool
    created_at: str
    started_at: str | None
    registered_as: str | None = Field(description="the registered model that uses it")
    model_state: str | None = Field(description="that model's wake/sleep state")
    model_detail: str | None = Field(
        None, description="why that model is starting or down, when known"
    )


class LogsOut(ResponseSchema):
    """The tail of a container's output."""

    name: str
    text: str
    truncated: bool


class GpuOut(ResponseSchema):
    """One GPU of a server."""

    index: int
    name: str
    memory_used_mb: int
    memory_total_mb: int
    utilization_pct: int
    temperature_c: int | None


class HostOut(ResponseSchema):
    """How loaded a server is."""

    gpus: list[GpuOut]
    gpu_error: str | None
    ram_total_mb: int
    ram_available_mb: int
    swap_total_mb: int
    swap_used_mb: int
    disk_total_gb: float
    disk_free_gb: float
    disk_path: str
    cpu_count: int
    load_1m: float
