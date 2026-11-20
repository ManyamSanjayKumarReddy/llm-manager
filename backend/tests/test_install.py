"""The public install script: the command a client runs on a GPU server."""

import asyncio
import shutil
from pathlib import Path

import httpx
import pytest

from llm_manager.api.routers.install import _SCRIPT
from tests.conftest import StackFactory


async def test_the_script_needs_no_login_and_names_this_wakeful(make_stack: StackFactory) -> None:
    stack = await make_stack()
    response = await stack.anonymous().get(
        "/install-agent.sh", headers={"Host": "wakeful.example.com"}
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-shellscript")
    assert response.headers["cache-control"] == "no-store"
    text = response.text
    assert 'CONNECT_URL="wss://wakeful.example.com/api/agent/connect"' in text
    assert "curl -fsSL https://wakeful.example.com/install-agent.sh" in text
    assert 'IMAGE="${WAKEFUL_AGENT_IMAGE:-wakeful/agent:latest}"' in text
    for placeholder in ("__WAKEFUL_URL__", "__CONNECT_URL__", "__AGENT_IMAGE__"):
        assert placeholder not in text


async def test_a_local_wakeful_uses_a_plain_websocket(make_stack: StackFactory) -> None:
    stack = await make_stack()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=stack.app), base_url="http://localhost:8040"
    ) as client:
        response = await client.get("/install-agent.sh")
    assert 'CONNECT_URL="ws://localhost:8040/api/agent/connect"' in response.text


async def test_the_image_comes_from_the_settings(make_stack: StackFactory) -> None:
    stack = await make_stack(agent_docker_image="acme/agent:1.2")
    response = await stack.anonymous().get("/install-agent.sh", headers={"Host": "w.example.com"})
    assert "acme/agent:1.2" in response.text


@pytest.mark.parametrize(
    "host", ['x"; rm -rf /; "', "a b", "$(id)", "evil.com/../x", "x`id`", "a;b"]
)
async def test_a_hostile_host_header_is_refused(make_stack: StackFactory, host: str) -> None:
    stack = await make_stack()
    response = await stack.anonymous().get("/install-agent.sh", headers={"Host": host})
    assert response.status_code == 400


async def test_a_bad_image_name_is_not_put_into_the_script(make_stack: StackFactory) -> None:
    stack = await make_stack(agent_docker_image='x"; reboot; "')
    response = await stack.anonymous().get("/install-agent.sh", headers={"Host": "w.example.com"})
    assert response.status_code == 500


async def test_the_rendered_script_is_valid_shell(make_stack: StackFactory, tmp_path: Path) -> None:
    stack = await make_stack()
    response = await stack.anonymous().get("/install-agent.sh", headers={"Host": "w.example.com"})
    script = tmp_path / "install.sh"
    script.write_text(response.text)
    bash = shutil.which("bash")
    assert bash is not None
    checked = await asyncio.create_subprocess_exec(bash, "-n", str(script))
    assert await checked.wait() == 0


def test_the_template_exists() -> None:
    assert _SCRIPT.is_file()
