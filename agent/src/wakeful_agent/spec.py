"""The container Wakeful may ask for, and how it becomes a ``docker run`` argument list.

Nothing here is ever given to a shell. The list is passed to ``docker`` directly, every field is
checked first, and secrets travel in the environment of the docker process (``-e NAME`` with no
value), so they never appear in a process listing.

The arguments mirror the command the dashboard shows (``web/src/lib/vllmCommand.ts``); the shared
fixture ``tests/golden_commands.json`` keeps the two in step.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from wakeful_agent.errors import SpecError
from wakeful_agent.settings import Settings

MANAGED_LABEL = "wakeful.managed"
LABEL_PORT = "wakeful.port"
LABEL_GPUS = "wakeful.gpus"
LABEL_MODEL = "wakeful.model"
CACHE_MOUNT = "/root/.cache/huggingface"

_NAME = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$"
_MODEL = r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)?$"
_PARSER = r"^[a-z0-9_]{1,40}$"
_EXTRA = re.compile(r"^[A-Za-z0-9_.:/=, @+-]{0,300}$")
_IMAGE = re.compile(r"^([a-z0-9][a-z0-9._/-]*):([A-Za-z0-9][A-Za-z0-9._-]{0,127})$")
_SECRET = re.compile(r"^[\x21-\x7e]{1,512}$")

# vLLM flags the agent sets itself: letting the caller repeat them would change what Wakeful needs.
_RESERVED_FLAGS = frozenset(
    {
        "--model",
        "--host",
        "--port",
        "--api-key",
        "--enable-sleep-mode",
        "--tensor-parallel-size",
        "-tp",
        "--max-model-len",
        "--max-num-seqs",
        "--gpu-memory-utilization",
        "--tokenizer-mode",
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "--download-dir",
        "--ssl-keyfile",
        "--ssl-certfile",
        "--trust-remote-code",
    }
)


class ContainerSpec(BaseModel):
    """A vLLM container with sleep mode switched on."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Field(pattern=_NAME)]
    model: Annotated[str, Field(pattern=_MODEL, max_length=200)]
    image: Annotated[str, Field(max_length=200, description="repository:tag, from the allowlist")]
    port: Annotated[int, Field(ge=1024, le=65535, description="on 127.0.0.1 of this server")]
    gpus: Annotated[list[int], Field(min_length=1, max_length=16)]
    cache_dir: Annotated[str, Field(max_length=300)]
    api_key: SecretStr | None = None
    hf_token: SecretStr | None = None
    max_model_len: Annotated[int, Field(ge=256)] = 8192
    max_num_seqs: Annotated[int, Field(ge=1)] = 16
    memory_share: Annotated[float, Field(ge=0.1, le=0.98)] = 0.9
    allow_long_context: bool = False
    tool_calling: bool = False
    tool_parser: Annotated[str, Field(pattern=_PARSER)] = "openai"
    auto_restart: bool = True
    extra_args: Annotated[str, Field(max_length=300)] = ""
    memory_gb: Annotated[int | None, Field(ge=1, le=2048)] = None
    cpus: Annotated[float | None, Field(gt=0, le=512)] = None


@dataclass(frozen=True)
class RunCommand:
    """Arguments for ``docker`` plus the secrets docker must read from its environment."""

    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)
    port: int = 0


def _check_secret(label: str, value: SecretStr | None) -> str | None:
    if value is None or value.get_secret_value() == "":
        return None
    text = value.get_secret_value()
    if not _SECRET.fullmatch(text):
        raise SpecError(f"{label}: one line, no spaces, up to 512 characters")
    return text


def _check_image(image: str, settings: Settings) -> None:
    match = _IMAGE.fullmatch(image)
    if match is None:
        raise SpecError("image: use repository:tag, for example vllm/vllm-openai:v0.10.1")
    if match.group(1) not in settings.images:
        allowed = ", ".join(settings.images)
        raise SpecError(f"image: only these repositories are allowed here: {allowed}")


def _check_cache_dir(raw: str, settings: Settings) -> Path:
    if not raw.startswith(("/", "~")) or any(c in raw for c in " \t\n\r:,\0"):
        raise SpecError("cache folder: an absolute path without spaces, colons or commas")
    path = Path(os.path.expanduser(raw))
    resolved = Path(os.path.realpath(path))
    for root in settings.cache_roots:
        root_resolved = Path(os.path.realpath(root))
        if resolved == root_resolved or root_resolved in resolved.parents:
            return resolved
    roots = ", ".join(str(r) for r in settings.cache_roots)
    raise SpecError(f"cache folder: must be inside {roots}")


def _check_extra(extra: str) -> list[str]:
    if not _EXTRA.fullmatch(extra):
        raise SpecError(
            "extra arguments: letters, digits and . : / = , @ + - only "
            "(no quotes or shell characters)"
        )
    tokens = extra.split()
    for token in tokens:
        flag = token.split("=", 1)[0]
        if flag in _RESERVED_FLAGS:
            raise SpecError(f"extra arguments: {flag} is set by Wakeful and cannot be repeated")
    return tokens


def build_run(spec: ContainerSpec, settings: Settings) -> RunCommand:
    """Validate ``spec`` against this server's rules and build the ``docker run`` arguments."""
    _check_image(spec.image, settings)
    cache = _check_cache_dir(spec.cache_dir, settings)
    extra = _check_extra(spec.extra_args)
    gpus = sorted(set(spec.gpus))
    if len(gpus) != len(spec.gpus) or gpus[0] < 0 or gpus[-1] >= settings.max_gpus:
        raise SpecError(f"gpus: distinct numbers from 0 to {settings.max_gpus - 1}")
    api_key = _check_secret("API key", spec.api_key)
    hf_token = _check_secret("Hugging Face token", spec.hf_token)

    env: dict[str, str] = {}
    argv = [
        "run",
        "-d",
        "--gpus",
        f'"device={",".join(str(g) for g in gpus)}"',  # docker wants the quotes in the value
        "--name",
        spec.name,
        "--label",
        f"{MANAGED_LABEL}=true",
        "--label",
        f"{LABEL_PORT}={spec.port}",
        "--label",
        f"{LABEL_GPUS}={','.join(str(g) for g in gpus)}",
        "--label",
        f"{LABEL_MODEL}={spec.model}",
    ]
    if spec.auto_restart:
        argv += ["--restart", "unless-stopped"]
    if spec.memory_gb is not None:
        argv += ["--memory", f"{spec.memory_gb}g", "--memory-swap", f"{spec.memory_gb}g"]
    if spec.cpus is not None:
        argv += ["--cpus", f"{spec.cpus:g}"]
    argv += ["-v", f"{cache}:{CACHE_MOUNT}"]
    if api_key:
        env["VLLM_API_KEY"] = api_key
        argv += ["-e", "VLLM_API_KEY"]
    if spec.allow_long_context:
        argv += ["-e", "VLLM_ALLOW_LONG_MAX_MODEL_LEN=1"]
    argv += ["-e", "VLLM_SERVER_DEV_MODE=1"]
    if hf_token:
        env["HUGGING_FACE_HUB_TOKEN"] = hf_token
        argv += ["-e", "HUGGING_FACE_HUB_TOKEN"]
    argv += ["-p", f"127.0.0.1:{spec.port}:8000", "--ipc=host", spec.image]
    argv += ["--model", spec.model]
    if len(gpus) > 1:
        argv += ["--tensor-parallel-size", str(len(gpus))]
    argv += [
        "--enable-sleep-mode",
        "--max-model-len",
        str(spec.max_model_len),
        "--max-num-seqs",
        str(spec.max_num_seqs),
        "--gpu-memory-utilization",
        f"{spec.memory_share:g}",
        "--tokenizer-mode",
        "auto",
    ]
    if spec.tool_calling:
        argv += ["--enable-auto-tool-choice", "--tool-call-parser", spec.tool_parser]
    argv += extra
    argv += ["--host", "0.0.0.0", "--port", "8000"]  # noqa: S104 - inside the container
    return RunCommand(argv=argv, env=env, port=spec.port)
