"""The agent's HTTP interface. Everything except ``/healthz`` needs the bearer token."""

import asyncio
import hmac
import logging
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

log = logging.getLogger(__name__)

_MAX_TAIL = 2000


class Host(Protocol):
    """Reads GPU, memory and disk figures."""

    async def read(self) -> HostOut:
        """The current figures."""
        ...


def create_app(settings: Settings, docker: Docker, host: Host) -> FastAPI:
    """The agent, wired to a Docker and a host reader."""
    app = FastAPI(title="Wakeful agent", version=__version__, docs_url=None, redoc_url=None)
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

    @app.post("/containers", dependencies=auth, status_code=status.HTTP_201_CREATED)
    async def create_container(spec: ContainerSpec) -> ContainerOut:
        command = build_run(spec, settings)
        async with changes:
            try:
                await docker.get(spec.name)
            except NotFoundError:
                pass
            else:
                raise AgentError(f"a container called '{spec.name}' already exists", 409)
            if not await docker.image_present(spec.image):
                raise AgentError(
                    f"image {spec.image} is not on this server yet: run 'docker pull "
                    f"{spec.image}' there first",
                    409,
                )
            await docker.run(command)
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
