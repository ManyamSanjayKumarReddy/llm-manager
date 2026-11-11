"""What a managed model looks like, and the scheduler's timing settings."""

import ipaddress
import re
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MAX_KEY_LENGTH = 512
_MAX_GPU_INDEX = 63


def _check_name(value: str) -> str:
    if not NAME_PATTERN.match(value):
        raise ValueError("name must be 1-64 characters: a-z, 0-9, dot, dash, underscore")
    return value


def _check_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("url must look like http://127.0.0.1:8025")
    if parts.username or parts.password:
        raise ValueError("url must not contain a username or password")
    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_link_local or address.is_unspecified):
        raise ValueError("that address cannot be a model container")
    return value.strip().rstrip("/")


def _check_gpus(value: frozenset[int]) -> frozenset[int]:
    if any(g < 0 or g > _MAX_GPU_INDEX for g in value):
        raise ValueError(f"GPU numbers must be between 0 and {_MAX_GPU_INDEX}")
    return value


def _check_api_key(value: SecretStr) -> SecretStr:
    """A key becomes an HTTP header, so it must be one printable line (no header injection)."""
    text = value.get_secret_value()
    if not text or text != text.strip() or not text.isprintable() or " " in text:
        raise ValueError("the key must be a single line without spaces")
    return value


ModelName = Annotated[str, AfterValidator(_check_name)]
ModelUrl = Annotated[str, Field(max_length=300), AfterValidator(_check_url)]
GpuSet = Annotated[frozenset[int], Field(min_length=1, max_length=16), AfterValidator(_check_gpus)]
ApiKeyText = Annotated[SecretStr, Field(max_length=_MAX_KEY_LENGTH), AfterValidator(_check_api_key)]
Priority = Annotated[int, Field(ge=0, le=100)]
IdleMinutes = Annotated[float, Field(gt=0, le=10_080)]


class ModelSpec(BaseModel):
    """One vLLM container managed by the router."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: ModelUrl = Field(description="vLLM base URL, e.g. http://127.0.0.1:8025")
    served_name: str | None = Field(None, max_length=200, description="name vLLM expects")
    gpus: GpuSet = Field(description="GPUs occupied while awake")
    idle_minutes: IdleMinutes = Field(10.0, description="sleep after this long without requests")
    priority: Priority = Field(
        0, description="higher wins when models that share a GPU are both waiting"
    )
    backend_api_key: ApiKeyText | None = Field(
        None, description="the container's own API key, if it was started with one"
    )

    @property
    def idle_seconds(self) -> float:
        """Idle timeout in seconds."""
        return self.idle_minutes * 60.0

    @property
    def backend_key(self) -> str | None:
        """The container's API key, or None. Only used to build the outgoing request header."""
        return self.backend_api_key.get_secret_value() if self.backend_api_key else None


class EngineConfig(BaseModel):
    """The wake/sleep scheduler's timings. The models themselves live in the database."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queue_timeout_s: float = Field(120.0, gt=0, description="max wait for a model to become ready")
    wake_timeout_s: float = Field(90.0, gt=0)
    sleep_timeout_s: float = Field(60.0, gt=0)
    min_awake_s: float = Field(10.0, ge=0, description="turn length when another model waits")
    priority_hold_s: float = Field(
        10.0,
        ge=0,
        description="a lower-priority model waits this long after a higher one last served",
    )
    reaper_interval_s: float = Field(15.0, gt=0)
    sleep_level: int = Field(1, ge=1, le=2, description="1 keeps weights in CPU RAM")
