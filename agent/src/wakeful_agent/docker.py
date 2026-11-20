"""Talking to the local Docker through its command-line tool.

Only containers carrying the ``wakeful.managed`` label are ever listed, changed or read: the other
containers on a shared server are invisible to the agent.
"""

import asyncio
import json
import logging
import os
from typing import Any, Protocol

from wakeful_agent.errors import AgentError, NotFoundError
from wakeful_agent.schemas import ContainerOut
from wakeful_agent.settings import Settings
from wakeful_agent.spec import LABEL_GPUS, LABEL_MODEL, LABEL_PORT, MANAGED_LABEL, RunCommand

log = logging.getLogger(__name__)

_MAX_LOG_BYTES = 200_000
_MAX_ERROR_CHARS = 600


class Docker(Protocol):
    """What the agent needs from Docker (a fake stands in for it in tests)."""

    async def list(self) -> list[ContainerOut]:
        """Every managed container."""
        ...

    async def get(self, name: str) -> ContainerOut:
        """One managed container, or ``NotFoundError``."""
        ...

    async def image_present(self, image: str) -> bool:
        """Whether the image is already on this server."""
        ...

    async def pull(self, image: str) -> None:
        """Download the image (it can be several gigabytes)."""
        ...

    async def run(self, command: RunCommand) -> None:
        """Create and start a container."""
        ...

    async def start(self, name: str) -> None:
        """Start a stopped container."""
        ...

    async def stop(self, name: str) -> None:
        """Stop a running container."""
        ...

    async def restart(self, name: str) -> None:
        """Restart a container."""
        ...

    async def remove(self, name: str) -> None:
        """Delete a container (stopping it first)."""
        ...

    async def logs(self, name: str, tail: int) -> tuple[str, bool]:
        """The last ``tail`` lines, and whether they were cut short."""
        ...


def _gpus(label: str | None) -> list[int]:
    if not label:
        return []
    return [int(g) for g in label.split(",") if g.isdigit()]


def _port(label: str | None) -> int | None:
    return int(label) if label and label.isdigit() else None


def parse_inspect(item: dict[str, Any]) -> ContainerOut:
    """A ``docker inspect`` entry as the agent reports it."""
    state = item.get("State") or {}
    config = item.get("Config") or {}
    labels = config.get("Labels") or {}
    host = item.get("HostConfig") or {}
    started = state.get("StartedAt")
    if not state.get("Running") and (started or "").startswith("0001-"):
        started = None
    running = bool(state.get("Running"))
    status = str(state.get("Status", "unknown"))
    return ContainerOut(
        name=str(item.get("Name", "")).lstrip("/"),
        state=status,
        running=running,
        status=status,
        image=str(config.get("Image", "")),
        port=_port(labels.get(LABEL_PORT)),
        gpus=_gpus(labels.get(LABEL_GPUS)),
        model=labels.get(LABEL_MODEL),
        restart_policy=str((host.get("RestartPolicy") or {}).get("Name") or "no"),
        exit_code=None if running else state.get("ExitCode"),
        oom_killed=bool(state.get("OOMKilled")),
        created_at=str(item.get("Created", "")),
        started_at=started,
    )


class CliDocker:
    """The real thing: runs ``docker`` as a subprocess."""

    def __init__(self, settings: Settings) -> None:
        self._bin = settings.docker_bin
        self._timeout = settings.command_timeout_s
        self._pull_timeout = settings.pull_timeout_s

    async def _exec(
        self, *args: str, env: dict[str, str] | None = None, limit_s: float | None = None
    ) -> tuple[int, bytes, bytes]:
        full_env = {**os.environ, **(env or {})}
        try:
            proc = await asyncio.create_subprocess_exec(
                self._bin,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=full_env,
            )
        except OSError as error:
            raise AgentError(f"cannot run '{self._bin}': {error}", 503) from error
        try:
            out, err = await asyncio.wait_for(proc.communicate(), limit_s or self._timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise AgentError("docker took too long to answer", 504) from None
        return proc.returncode or 0, out, err

    async def _ok(
        self, *args: str, env: dict[str, str] | None = None, limit_s: float | None = None
    ) -> bytes:
        code, out, err = await self._exec(*args, env=env, limit_s=limit_s)
        if code != 0:
            message = err.decode(errors="replace").strip()[:_MAX_ERROR_CHARS]
            raise AgentError(f"docker {args[0]} failed: {message or 'no details'}", 502)
        return out

    async def _inspect(self, *names: str) -> list[dict[str, Any]]:
        code, out, _ = await self._exec("inspect", "--type", "container", *names)
        if code != 0:
            return []
        data = json.loads(out or b"[]")
        return [d for d in data if (d.get("Config") or {}).get("Labels", {}).get(MANAGED_LABEL)]

    async def list(self) -> list[ContainerOut]:
        """Every managed container, by name."""
        ids = (
            await self._ok("ps", "-aq", "--no-trunc", "--filter", f"label={MANAGED_LABEL}=true")
        ).split()
        if not ids:
            return []
        items = await self._inspect(*(i.decode() for i in ids))
        return sorted((parse_inspect(i) for i in items), key=lambda c: c.name)

    async def get(self, name: str) -> ContainerOut:
        """One managed container, or ``NotFoundError``."""
        found = await self._inspect(name)
        if not found:
            raise NotFoundError(name)
        return parse_inspect(found[0])

    async def image_present(self, image: str) -> bool:
        """Whether ``docker image inspect`` finds it."""
        code, _, _ = await self._exec("image", "inspect", image)
        return code == 0

    async def pull(self, image: str) -> None:
        """``docker pull``; the image was checked against the allowlist before it got here."""
        try:
            await self._ok("pull", "--quiet", image, limit_s=self._pull_timeout)
        except AgentError as error:
            raise AgentError(
                f"{error.message} (if '{image}' is an image you build on this server, build it "
                "there first)",
                error.status,
            ) from error

    async def run(self, command: RunCommand) -> None:
        """``docker run -d`` with the secrets in the process environment."""
        try:
            await self._ok(*command.argv, env=command.env)
        except AgentError as error:
            if "is already in use" not in error.message:
                raise
            name = command.argv[command.argv.index("--name") + 1]
            raise AgentError(
                f"a container called '{name}' already exists on this server but was not created "
                f"by Wakeful (for example a stopped one from an earlier manual try). Remove it "
                f"there with 'docker rm -f {name}', or choose another name",
                409,
            ) from error

    async def _on(self, verb: str, name: str, *extra: str) -> None:
        await self.get(name)  # refuses anything this agent did not create
        await self._ok(verb, *extra, name)

    async def start(self, name: str) -> None:
        """Start it."""
        await self._on("start", name)

    async def stop(self, name: str) -> None:
        """Stop it, giving vLLM 30 s to shut down."""
        await self._on("stop", name, "-t", "30")

    async def restart(self, name: str) -> None:
        """Restart it."""
        await self._on("restart", name, "-t", "30")

    async def remove(self, name: str) -> None:
        """Delete it, forcing a stop if it is running."""
        await self._on("rm", name, "-f")

    async def logs(self, name: str, tail: int) -> tuple[str, bool]:
        """The last ``tail`` lines of stdout and stderr together."""
        await self.get(name)
        code, out, err = await self._exec("logs", "--tail", str(tail), "--timestamps", name)
        if code != 0:
            raise AgentError("docker logs failed", 502)
        data = out + err  # vLLM writes to both; timestamps keep the order readable
        text = data.decode(errors="replace")
        truncated = len(data) > _MAX_LOG_BYTES
        return (text[-_MAX_LOG_BYTES:] if truncated else text), truncated
