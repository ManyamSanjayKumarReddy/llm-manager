from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from tests.fakes import FakeDocker, FakeHost
from wakeful_agent.app import create_app
from wakeful_agent.settings import Settings

TOKEN = "t" * 40


@pytest.fixture
def cache_root(tmp_path: Path) -> Path:
    root = tmp_path / "cache"
    root.mkdir()
    return root


@pytest.fixture
def settings(cache_root: Path) -> Settings:
    return Settings(token=TOKEN, cache_roots=[cache_root])


@pytest.fixture
def docker() -> FakeDocker:
    return FakeDocker()


@pytest_asyncio.fixture
async def client(settings: Settings, docker: FakeDocker) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, docker, FakeHost())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://agent", headers={"Authorization": f"Bearer {TOKEN}"}
    ) as c:
        yield c
