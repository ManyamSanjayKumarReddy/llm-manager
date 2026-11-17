from pathlib import Path

import httpx
import pytest

from tests.conftest import TOKEN
from tests.fakes import FakeDocker


def body(cache_root: Path, **changes: object) -> dict[str, object]:
    return {
        "name": "qwen",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "image": "vllm/vllm-openai:v0.10.1",
        "port": 8026,
        "gpus": [0],
        "cache_dir": str(cache_root / "hf"),
        **changes,
    }


async def test_health_needs_no_token(client: httpx.AsyncClient) -> None:
    response = await client.get("/healthz", headers={"Authorization": ""})
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.parametrize("header", ["", "Bearer wrong", f"Basic {TOKEN}", "Bearer"])
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/containers"),
        ("GET", "/host"),
        ("POST", "/containers"),
        ("POST", "/containers/qwen/stop"),
        ("DELETE", "/containers/qwen"),
        ("GET", "/containers/qwen/logs"),
    ],
)
async def test_everything_else_needs_the_token(
    client: httpx.AsyncClient, method: str, path: str, header: str
) -> None:
    response = await client.request(method, path, headers={"Authorization": header})
    assert response.status_code == 401


async def test_create_list_stop_start_restart_logs_remove(
    client: httpx.AsyncClient, cache_root: Path, docker: FakeDocker
) -> None:
    created = await client.post("/containers", json=body(cache_root))
    assert created.status_code == 201
    assert created.json()["name"] == "qwen"
    assert created.json()["gpus"] == [0]
    assert created.json()["port"] == 8026

    assert [c["name"] for c in (await client.get("/containers")).json()] == ["qwen"]

    stopped = await client.post("/containers/qwen/stop")
    assert stopped.json()["running"] is False
    started = await client.post("/containers/qwen/start")
    assert started.json()["running"] is True
    assert (await client.post("/containers/qwen/restart")).status_code == 200

    logs = await client.get("/containers/qwen/logs", params={"tail": 50})
    assert logs.json()["text"] == "last 50 lines of qwen\n"

    assert (await client.delete("/containers/qwen")).status_code == 204
    assert (await client.get("/containers")).json() == []
    assert [c[0] for c in docker.calls] == ["stop", "start", "restart", "remove"]


async def test_containers_the_agent_did_not_create_are_invisible_and_untouchable(
    client: httpx.AsyncClient, docker: FakeDocker
) -> None:
    for method, path in [
        ("GET", "/containers/production-db"),
        ("POST", "/containers/production-db/stop"),
        ("POST", "/containers/production-db/start"),
        ("POST", "/containers/production-db/restart"),
        ("DELETE", "/containers/production-db"),
        ("GET", "/containers/production-db/logs"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 404, path
    assert docker.calls == []
    assert (await client.get("/containers")).json() == []


async def test_a_second_container_with_the_same_name_is_refused(
    client: httpx.AsyncClient, cache_root: Path
) -> None:
    assert (await client.post("/containers", json=body(cache_root))).status_code == 201
    again = await client.post("/containers", json=body(cache_root))
    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]


async def test_a_name_used_by_another_container_is_reported_by_docker(
    client: httpx.AsyncClient, cache_root: Path
) -> None:
    response = await client.post("/containers", json=body(cache_root, name="production-db"))
    assert response.status_code == 502


async def test_the_image_must_already_be_on_the_server(
    client: httpx.AsyncClient, cache_root: Path, docker: FakeDocker
) -> None:
    docker.images.clear()
    response = await client.post("/containers", json=body(cache_root))
    assert response.status_code == 409
    assert "docker pull vllm/vllm-openai:v0.10.1" in response.json()["detail"]
    assert docker.runs == []


async def test_rule_breaking_specs_never_reach_docker(
    client: httpx.AsyncClient, cache_root: Path, docker: FakeDocker
) -> None:
    for changes in [
        {"image": "evil/miner:1"},
        {"cache_dir": "/etc"},
        {"extra_args": "--host 1.2.3.4"},
        {"extra_args": "; reboot"},
        {"name": "a b"},
    ]:
        response = await client.post("/containers", json=body(cache_root, **changes))
        assert response.status_code == 422, changes
        assert isinstance(response.json()["detail"], str)
    assert docker.runs == []


async def test_secrets_are_never_returned(
    client: httpx.AsyncClient, cache_root: Path, docker: FakeDocker
) -> None:
    created = await client.post(
        "/containers", json=body(cache_root, api_key="sk-very-secret", hf_token="hf_abc")
    )
    assert created.status_code == 201
    assert "sk-very-secret" not in created.text
    assert "hf_abc" not in created.text
    assert docker.runs[0].env["VLLM_API_KEY"] == "sk-very-secret"


async def test_host_figures(client: httpx.AsyncClient) -> None:
    host = (await client.get("/host")).json()
    assert host["gpus"][0]["memory_total_mb"] == 16311
    assert host["ram_available_mb"] == 20000


async def test_log_tail_is_bounded(client: httpx.AsyncClient, cache_root: Path) -> None:
    await client.post("/containers", json=body(cache_root))
    assert (await client.get("/containers/qwen/logs", params={"tail": 0})).status_code == 422
    assert (await client.get("/containers/qwen/logs", params={"tail": 99999})).status_code == 422
