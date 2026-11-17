"""The agent's settings, read from ``AGENT_*`` environment variables."""

import os
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MIN_TOKEN_LENGTH = 32


def _home_cache() -> list[Path]:
    return [Path(os.path.expanduser("~/.cache"))]


class Settings(BaseSettings):
    """What this server allows Wakeful to do."""

    model_config = SettingsConfigDict(
        env_prefix="AGENT_", env_file=(".env",), extra="ignore", case_sensitive=False
    )

    token: str = Field(
        min_length=MIN_TOKEN_LENGTH,
        description="the secret Wakeful sends as 'Authorization: Bearer <token>'",
    )
    cache_roots: Annotated[list[Path], NoDecode] = Field(
        default_factory=_home_cache,
        description="the only folders a container may mount (comma-separated)",
    )
    images: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["vllm/vllm-openai", "vllm-openai"],
        description="the only image repositories a container may use (comma-separated)",
    )
    docker_bin: str = "docker"
    nvidia_smi_bin: str = "nvidia-smi"
    command_timeout_s: float = Field(60.0, gt=0, description="longest one docker command may take")
    max_gpus: int = Field(16, ge=1)

    @field_validator("cache_roots", mode="before")
    @classmethod
    def _split_roots(cls, value: object) -> object:
        if isinstance(value, str):
            return [Path(os.path.expanduser(p.strip())) for p in value.split(",") if p.strip()]
        return value

    @field_validator("images", mode="before")
    @classmethod
    def _split_images(cls, value: object) -> object:
        if isinstance(value, str):
            return [p.strip() for p in value.split(",") if p.strip()]
        return value
