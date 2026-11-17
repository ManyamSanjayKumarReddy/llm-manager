"""Schemas for the servers (machines with GPUs) that models are placed on."""

import ipaddress
from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field

from llm_manager.core.models_config import ServerName
from llm_manager.schemas.base import RequestSchema, ResponseSchema

GpuCount = Annotated[int, Field(ge=1, le=16)]
GpuType = Annotated[str, Field(max_length=100)]
MIN_AGENT_TOKEN = 32


def _check_agent_url(value: str) -> str:
    """An address like https://gpu-box.example.com/agent (empty clears it; http only locally)."""
    text = value.strip().rstrip("/")
    if not text:
        return ""
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("agent address must look like https://gpu-box.example.com/agent")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("agent address must not contain a login, query or fragment")
    if parts.scheme == "http":
        host = parts.hostname
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "localhost"
        if not local:
            raise ValueError(
                "the token would travel unencrypted: use https (http only for localhost)"
            )
    return text


AgentUrl = Annotated[str, Field(max_length=300), AfterValidator(_check_agent_url)]
AgentToken = Annotated[
    str, Field(min_length=MIN_AGENT_TOKEN, max_length=512, pattern=r"^[\x21-\x7e]+$")
]


class ServerCreate(RequestSchema):
    """A machine to place models on."""

    name: ServerName = Field(description="a short label, e.g. gpu-box-2")
    gpu_count: GpuCount = Field(description="how many GPUs it has (numbered from 0)")
    gpu_type: GpuType | None = Field(
        None, description="what kind of GPUs, e.g. 2x RTX 4060 Ti 16 GB"
    )
    agent_url: AgentUrl | None = Field(None, description="where the Wakeful agent on it listens")
    agent_token: AgentToken | None = Field(None, description="the agent's secret (write-only)")


class ServerUpdate(RequestSchema):
    """What can change on a server (the name cannot: models refer to it)."""

    gpu_count: GpuCount | None = None
    gpu_type: GpuType | None = Field(None, description="empty text clears it")
    agent_url: AgentUrl | None = Field(None, description="empty text removes the agent")
    agent_token: AgentToken | None = Field(None, description="replaces the stored token")


class ServerOut(ResponseSchema):
    """A server and the models placed on it."""

    name: str
    gpu_count: int
    gpu_type: str | None
    agent_url: str | None
    has_agent: bool = Field(description="an agent address and token are stored (token never shown)")
    models: list[str]
    created_at: datetime
