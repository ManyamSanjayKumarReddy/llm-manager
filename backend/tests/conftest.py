"""Shared fixtures: a real PostgreSQL, the full app wired to fake vLLM containers."""

import asyncio
import contextlib
import os
import secrets
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from tortoise.contrib.test import tortoise_test_context

from llm_manager.api.container import Container
from llm_manager.core.models_config import EngineConfig
from llm_manager.core.settings import Settings
from llm_manager.db.models import ManagedModel, Role, Server, User
from llm_manager.main import create_app
from llm_manager.services.tunnel import Hub, TunnelRouter
from tests.fakes import Dispatch, FakeVLLM, Ledger

GPUS = {
    "a": frozenset({0, 1}),
    "b": frozenset({0}),
    "c": frozenset({1}),
    "d": frozenset({2}),  # a running container that is NOT registered until a test registers it
}
PORTS = {"a": 9001, "b": 9002, "c": 9003, "d": 9004}
CONFIGURED = ("a", "b", "c")
ADMIN_PASSWORD = "correct-horse-battery"
HTTPS = "https://testserver"  # the Secure session cookie is only sent over https


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A throw-away PostgreSQL (Docker), or the one named by TEST_DATABASE_URL."""
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    if shutil.which("docker") is None:
        pytest.skip("Docker is needed for the PostgreSQL tests (or set TEST_DATABASE_URL)")
    password = secrets.token_hex(8)
    container = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "-e",
            f"POSTGRES_PASSWORD={password}",
            "-p",
            "127.0.0.1::5432",
            "--tmpfs",
            "/var/lib/postgresql/data",
            "postgres:16-alpine",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    try:
        port = (
            subprocess.run(
                ["docker", "port", container, "5432/tcp"],
                capture_output=True,
                text=True,
                check=True,
            )
            .stdout.split(":")[-1]
            .strip()
        )
        for _ in range(60):
            ready = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-U", "postgres"],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        time.sleep(1)  # pg_isready can answer before the init restart finishes
        yield f"postgres://postgres:{password}@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


def _with_database(url: str, name: str) -> str:
    """Return ``url`` pointing at database ``name``."""
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


@pytest_asyncio.fixture
async def db(postgres_url: str) -> AsyncIterator[None]:
    """A fresh, empty database for one test (created by Tortoise, dropped afterwards)."""
    name = f"test_{secrets.token_hex(4)}"  # generated here, never user input
    try:
        async with tortoise_test_context(
            ["llm_manager.db.models"], db_url=_with_database(postgres_url, name)
        ):
            yield
    finally:
        admin = await asyncpg.connect(postgres_url)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await admin.close()


@dataclass
class Stack:
    """The whole application plus its fake vLLM containers."""

    app: FastAPI
    container: Container
    fakes: dict[str, FakeVLLM]
    ledger: Ledger
    dispatch: Dispatch
    hub: Hub
    _clients: list[httpx.AsyncClient] = field(default_factory=list)

    def anonymous(self) -> httpx.AsyncClient:
        """A client with no cookies and no API key."""
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url=HTTPS, timeout=30
        )
        self._clients.append(client)
        return client

    async def create_user(
        self, username: str = "admin", role: Role = Role.ADMIN, password: str = ADMIN_PASSWORD
    ) -> User:
        return await self.container.users.create(username, password, role, actor="test")

    async def login(
        self, username: str = "admin", password: str = ADMIN_PASSWORD
    ) -> httpx.AsyncClient:
        """A client logged in as ``username`` (cookie jar + CSRF header already set)."""
        client = self.anonymous()
        response = await client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client

    async def api_key(
        self,
        label: str = "test",
        *,
        allowed_models: list[str] | None = None,
        rpm_limit: int | None = None,
    ) -> str:
        _, token = await self.container.api_keys.create(
            label,
            created_by=None,
            allowed_models=allowed_models,
            rpm_limit=rpm_limit,
            actor="test",
        )
        return token

    async def chat(self, token: str, model: str, **extra: object) -> httpx.Response:
        client = self.anonymous()
        return await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": model, "messages": [], **extra},
        )


StackFactory = Callable[..., Awaitable[Stack]]


@pytest_asyncio.fixture
async def make_stack(db: None, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[StackFactory]:
    """Factory building the app; keyword arguments override engine and settings values."""
    # The real values are seconds; the tests only need the order of events.
    monkeypatch.setattr("llm_manager.engine.manager._ABORT_SETTLE_S", 0.1)
    monkeypatch.setattr("llm_manager.engine.manager._CALIBRATE_GAP_S", 0.05)
    monkeypatch.setattr("llm_manager.engine.manager._QUIET_S", 0.2)
    monkeypatch.setattr("llm_manager.engine.manager._QUIET_LIMIT_S", 3.0)
    monkeypatch.setattr("llm_manager.engine.backend._POLL_S", 0.05)
    monkeypatch.setattr("llm_manager.engine.manager._DOWN_RETRY_GAP_S", 0.05)
    monkeypatch.setattr("llm_manager.engine.manager._REPROBE_GAP_S", 0.05)
    cleanups: list[tuple[contextlib.AbstractAsyncContextManager[Any], Stack]] = []

    async def _make(**overrides: object) -> Stack:
        idle_minutes = float(cast("float", overrides.pop("idle_minutes", 60.0)))
        priorities = cast("dict[str, int]", overrides.pop("priorities", {}))
        registered = cast("tuple[str, ...]", overrides.pop("models", CONFIGURED))
        engine_keys = {
            "queue_timeout_s",
            "wake_timeout_s",
            "sleep_timeout_s",
            "min_awake_s",
            "preempt_after_s",
            "reaper_interval_s",
        }
        engine_opts = {
            "queue_timeout_s": 10.0,
            "wake_timeout_s": 5.0,
            "sleep_timeout_s": 5.0,
            "min_awake_s": 0.1,
            "priority_hold_s": 0.1,
            "reaper_interval_s": 0.05,
        }
        engine_opts.update({k: cast("float", v) for k, v in overrides.items() if k in engine_keys})
        settings_opts = {k: v for k, v in overrides.items() if k not in engine_keys}

        ledger = Ledger(GPUS)
        fakes = {n: FakeVLLM(n, ledger) for n in GPUS}
        ledger.violations.clear()  # real containers are started one at a time (bootstrap script)
        # Models are registered in the database, as the dashboard does it.
        server = await Server.create(name="this-server", gpu_count=8)
        await Server.create(name="gpu-box-2", gpu_count=2)
        await ManagedModel.bulk_create(
            [
                ManagedModel(
                    name=n,
                    server=server,
                    url=f"http://127.0.0.1:{PORTS[n]}",
                    served_name=f"org/{n}",
                    gpus=sorted(GPUS[n]),
                    idle_minutes=idle_minutes,
                    priority=priorities.get(n, 0),
                )
                for n in registered
            ]
        )
        config = EngineConfig(**engine_opts)
        settings = Settings(
            _env_file=None, database_url="unused", **cast("dict[str, Any]", settings_opts)
        )
        dispatch = Dispatch({PORTS[n]: f.app for n, f in fakes.items()})
        hub = Hub()
        backend = httpx.AsyncClient(transport=TunnelRouter(hub, dispatch))
        app = create_app(settings, config, http_client=backend, hub=hub, manage_orm=False)
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        await app.state.container.manager.wait_until_started()  # the server answers before this
        stack = Stack(app, app.state.container, fakes, ledger, dispatch, hub)
        cleanups.append((lifespan, stack))
        return stack

    yield _make
    for lifespan, stack in cleanups:
        for client in stack._clients:
            await client.aclose()
        await lifespan.__aexit__(None, None, None)


def model_state(stack: Stack, name: str) -> str:
    """The engine's current state of a model, e.g. ``"awake"``."""
    return stack.container.manager.models[name].state.value


async def eventually(check: Callable[[], Awaitable[bool]], timeout_s: float = 3.0) -> None:
    """Poll until ``check`` is true (for things written by background tasks)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


async def until_busy(stack: Stack, name: str) -> None:
    """Wait until a request to ``name`` is really being served (a fixed sleep is not reliable)."""

    async def busy() -> bool:
        return stack.container.manager.models[name].inflight > 0

    await eventually(busy, timeout_s=10.0)
