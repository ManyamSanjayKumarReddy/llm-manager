"""The agent's HTTP interface. Everything except ``/healthz`` needs the bearer token."""

import asyncio
import contextlib
import hmac
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from wakeful_agent import __version__
from wakeful_agent.docker import Docker
from wakeful_agent.errors import AgentError, NotFoundError
from wakeful_agent.schemas import ContainerOut, HealthOut, HostOut, LogsOut
from wakeful_agent.settings import Settings
from wakeful_agent.spec import ContainerSpec, build_run
from wakeful_agent.tunnel import Tunnel

log = logging.getLogger(__name__)

_MAX_TAIL = 2000


class Host(Protocol):
    """Reads GPU, memory and disk figures."""

    async def read(self) -> HostOut:
        """The current figures."""
        ...


def create_app(settings: Settings, docker: Docker, host: Host) -> FastAPI:
    """The agent, wired to a Docker and a host reader."""

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # With AGENT_CONNECT_URL the agent also dials out to Wakeful for as long as it runs.
        if not settings.connect_url:
            yield
            return
        task = asyncio.create_task(Tunnel(settings, app, docker).run(), name="tunnel")
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(
        title="Wakeful agent",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    token = settings.token.encode()
    changes = asyncio.Lock()  # one container change at a time

    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        supplied = (authorization or "").removeprefix("Bearer ").strip().encode()
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong or missing token")

    auth = [Depends(require_token)]

    @app.exception_handler(AgentError)
    async def _agent_error(_: Request, error: AgentError) -> JSONResponse:
        return JSONResponse({"detail": error.message}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, error: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'][1:]) or 'body'}: {e['msg']}"
            for e in error.errors()
        )
        return JSONResponse({"detail": problems}, status_code=422)

    @app.get("/healthz")
    async def healthz() -> HealthOut:
        return HealthOut(ok=True, version=__version__)

    @app.get("/host", dependencies=auth)
    async def read_host() -> HostOut:
        return await host.read()

    @app.get("/containers", dependencies=auth)
    async def list_containers() -> list[ContainerOut]:
        return await docker.list()

    @app.get("/containers/{name}", dependencies=auth)
    async def get_container(name: str) -> ContainerOut:
        return await docker.get(name)

    async def _ensure_unused(name: str) -> None:
        try:
            await docker.get(name)
        except NotFoundError:
            return
        raise AgentError(f"a container called '{name}' already exists", 409)

    @app.post("/containers", dependencies=auth, status_code=status.HTTP_201_CREATED)
    async def create_container(spec: ContainerSpec) -> ContainerOut:
        command = build_run(spec, settings)
        await _ensure_unused(spec.name)
        if not await docker.image_present(spec.image):
            # Not under the lock: downloading can take minutes and must not hold up other changes.
            log.info("downloading image %s for %s", spec.image, spec.name)
            await docker.pull(spec.image)
        async with changes:
            await _ensure_unused(spec.name)
            try:
                await docker.run(command)
            except AgentError:
                # Docker may leave a half-made container behind (for example when the GPU driver
                # is missing); it would block the next try with "already exists". Only a container
                # this agent manages can be removed, so a name taken by someone else is left alone.
                with contextlib.suppress(AgentError):
                    await docker.remove(spec.name)
                raise
            log.info("created container %s (%s) on port %s", spec.name, spec.image, spec.port)
        return await docker.get(spec.name)

    @app.post("/containers/{name}/start", dependencies=auth)
    async def start_container(name: str) -> ContainerOut:
        async with changes:
            await docker.start(name)
        return await docker.get(name)

    @app.post("/containers/{name}/stop", dependencies=auth)
    async def stop_container(name: str) -> ContainerOut:
        async with changes:
            await docker.stop(name)
        return await docker.get(name)

    @app.post("/containers/{name}/restart", dependencies=auth)
    async def restart_container(name: str) -> ContainerOut:
        async with changes:
            await docker.restart(name)
        return await docker.get(name)

    @app.delete("/containers/{name}", dependencies=auth, status_code=status.HTTP_204_NO_CONTENT)
    async def remove_container(name: str) -> Response:
        async with changes:
            await docker.remove(name)
        log.info("removed container %s", name)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/containers/{name}/logs", dependencies=auth)
    async def container_logs(
        name: str, tail: Annotated[int, Query(ge=1, le=_MAX_TAIL)] = 200
    ) -> LogsOut:
        text, truncated = await docker.logs(name, tail)
        return LogsOut(name=name, text=text, truncated=truncated)

    return app
