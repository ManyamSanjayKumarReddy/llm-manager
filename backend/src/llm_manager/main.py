"""Application factory and startup/shutdown wiring."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI
from tortoise.contrib.fastapi import RegisterTortoise

from llm_manager.api.container import build_container
from llm_manager.api.errors import register_exception_handlers
from llm_manager.api.middleware import OriginCheckMiddleware, SecurityHeadersMiddleware
from llm_manager.api.routers import (
    agent_connect,
    api_keys,
    auth,
    containers,
    health,
    install,
    models,
    proxy,
    scheduling,
    servers,
    status,
    usage,
    users,
)
from llm_manager.api.spa import SpaStaticFiles
from llm_manager.core.logging import configure_logging, keep_query_parameters_out_of_logs
from llm_manager.core.models_config import EngineConfig
from llm_manager.core.settings import Settings, get_settings
from llm_manager.db.config import build_tortoise_config
from llm_manager.db.models import Server
from llm_manager.engine import Manager
from llm_manager.engine.backend import VllmBackend
from llm_manager.services.maintenance import run_maintenance
from llm_manager.services.models import ModelStore
from llm_manager.services.scheduler_settings import stored_engine_config
from llm_manager.services.tunnel import Hub, TunnelRouter

_CONNECT_TIMEOUT_S = 5.0
_WRITE_TIMEOUT_S = 30.0

log = logging.getLogger(__name__)


async def _run_manager(manager: Manager) -> None:
    """Check where every container is, then keep the idle-sleep reaper running."""
    try:
        await manager.startup()
    except Exception:
        # Requests are released either way; the reaper re-adopts containers it can reach later.
        log.exception("startup check failed")
    await manager.run_reaper()


def create_app(
    settings: Settings,
    engine_config: EngineConfig | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
    hub: Hub | None = None,
    manage_orm: bool = True,
) -> FastAPI:
    """Build the application.

    Args:
        settings: Security and infrastructure settings.
        engine_config: Scheduler timings (tests); by default the saved ones, else ``settings``.
        http_client: Client used to reach the vLLM containers (tests inject a fake).
        hub: Holds the connections of agents that dial in (tests inject one their client uses).
        manage_orm: Connect to the database at startup. Tests that already did pass False.
    """
    keep_query_parameters_out_of_logs()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            if manage_orm:
                await stack.enter_async_context(
                    RegisterTortoise(app, config=build_tortoise_config(settings.database_url))
                )
            tunnels = hub or Hub()
            tunnels.set_tunneled(
                {row.name for row in await Server.filter(tunnel_token_hash__not_isnull=True)}
            )
            http = http_client
            if http is None:
                http = httpx.AsyncClient(
                    transport=TunnelRouter(tunnels, httpx.AsyncHTTPTransport()),
                    timeout=httpx.Timeout(
                        connect=_CONNECT_TIMEOUT_S, read=None, write=_WRITE_TIMEOUT_S, pool=None
                    ),
                )
                stack.push_async_callback(http.aclose)
            # Admins change the timings in the dashboard; they win over the environment.
            timings = engine_config or await stored_engine_config(settings)
            backend = VllmBackend(
                http,
                sleep_level=timings.sleep_level,
                sleep_timeout_s=timings.sleep_timeout_s,
                wake_timeout_s=timings.wake_timeout_s,
            )
            # Models are registered in the dashboard and kept in the database.
            models = await ModelStore.specs()
            container = build_container(
                settings, Manager(timings, backend, models, starting=True), http, tunnels
            )
            app.state.container = container
            refreshes: set[asyncio.Task[None]] = set()

            def agent_connected(server: str) -> None:
                """Look at the server's models at once: they were unreachable until now."""
                for model in container.manager.models.values():
                    if model.spec.server == server:
                        task = asyncio.create_task(container.manager.refresh(model.name))
                        refreshes.add(task)
                        task.add_done_callback(refreshes.discard)

            tunnels.on_connected = agent_connected
            container.manager.diagnose = container.containers.diagnose
            container.manager.event_sink = container.recorder.record_event

            background = [
                asyncio.create_task(container.recorder.run(), name="recorder"),
                asyncio.create_task(run_maintenance(settings), name="maintenance"),
            ]
            # The server answers at once; requests for a model wait until this has finished.
            background.append(asyncio.create_task(_run_manager(container.manager), name="manager"))
            try:
                yield
            finally:
                for task in background:
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.gather(*background)
                await container.manager.aclose()

    # The interactive API docs are switched off: this is an internal tool, so there is no
    # reason to publish its schema.
    app = FastAPI(
        title="llm-manager",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # The last middleware added is the outermost one.
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
    register_exception_handlers(app)
    for module in (
        health,
        install,
        agent_connect,
        auth,
        users,
        api_keys,
        servers,
        containers,
        models,
        scheduling,
        status,
        usage,
        proxy,
    ):
        app.include_router(module.router)
    dist = settings.web_dist_path
    if dist is not None and (dist / "index.html").is_file():
        # Mounted last, so every API route above wins.
        app.mount("/", SpaStaticFiles(directory=dist), name="dashboard")
    return app


def app_from_env() -> FastAPI:
    """Entry point for ``uvicorn --factory llm_manager.main:app_from_env``."""
    settings = get_settings()
    configure_logging(settings.log_level)
    return create_app(settings)
