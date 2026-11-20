"""The agent's settings, read from ``AGENT_*`` environment variables."""

import os
import secrets
from pathlib import Path
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
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
        "",
        description="the secret Wakeful sends as 'Authorization: Bearer <token>' when it calls "
        "this agent over HTTP; not needed when the agent connects out (connect_url)",
    )
    connect_url: str | None = Field(
        None,
        description="wss://... address of Wakeful's /api/agent/connect: the agent then connects "
        "out and needs no open port",
    )
    connect_token: str = Field(
        "", description="the enrollment token Wakeful showed for this server"
    )
    relay_ports: Annotated[list[int], NoDecode] = Field(
        default_factory=list,
        description="ports of vLLM containers NOT created by this agent that Wakeful may reach "
        "through the outbound connection (comma-separated)",
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

    @model_validator(mode="after")
    def _check_access(self) -> Self:
        """Either Wakeful calls in (token) or the agent connects out (connect_url + token)."""
        if self.token and len(self.token) < MIN_TOKEN_LENGTH:
            raise ValueError(f"AGENT_TOKEN must be at least {MIN_TOKEN_LENGTH} characters")
        if self.connect_url:
            if len(self.connect_token) < MIN_TOKEN_LENGTH:
                raise ValueError("AGENT_CONNECT_TOKEN is missing or too short")
            parts = urlsplit(self.connect_url)
            local = parts.hostname in {"localhost", "127.0.0.1", "::1"}
            if parts.scheme != "wss" and not (parts.scheme == "ws" and local):
                raise ValueError(
                    "AGENT_CONNECT_URL must start with wss:// (ws:// only for localhost): the "
                    "token would travel unencrypted"
                )
            if not self.token:
                # Nobody can call this agent over HTTP: only the outbound connection is used.
                self.token = secrets.token_hex(32)
        elif not self.token:
            raise ValueError(
                "set AGENT_TOKEN (Wakeful calls in) or AGENT_CONNECT_URL (it dials out)"
            )
        return self

    @field_validator("relay_ports", mode="before")
    @classmethod
    def _split_ports(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(p) for p in value.split(",") if p.strip()]
        return value

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
