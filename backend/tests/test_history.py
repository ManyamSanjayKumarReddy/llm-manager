"""Requests and events are persisted; the dashboard endpoints read them back."""

from llm_manager.db.models import Event, RequestLog
from tests.conftest import StackFactory, eventually


async def test_requests_are_persisted_without_content(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    token = await stack.api_key("ci")
    for _ in range(3):
        assert (await stack.chat(token, "a")).status_code == 200

    async def written() -> bool:
        return await RequestLog.filter(model="a").count() == 3

    await eventually(written)
    row = await RequestLog.filter(model="a").first()
    assert row is not None
    assert row.status == 200
    assert await RequestLog.filter(model="a", api_key_id__isnull=False).count() == 3
    # only metadata is stored, never prompts or responses
    assert not any(n in RequestLog._meta.fields_map for n in ("body", "prompt", "response"))


async def test_events_survive_in_the_database(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    token = await stack.api_key()
    await stack.chat(token, "a")

    async def written() -> bool:
        return await Event.filter(model="a", kind="woke").exists()

    await eventually(written)


async def test_stats_endpoint_reports_per_model_history(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    token = await stack.api_key()
    await stack.chat(token, "a")
    await stack.chat(token, "a")
    await stack.chat(token, "nope")  # 404, not logged: it never reached a model

    async def written() -> bool:
        return await RequestLog.filter(model="a").count() == 2

    await eventually(written)
    client = await stack.login()
    stats = (await client.get("/api/stats?hours=1")).json()
    assert stats["total"] == 1
    (entry,) = stats["items"]
    assert entry["model"] == "a"
    assert entry["requests"] == 2
    assert entry["errors"] == 0
    assert entry["p95_ms"] is not None


async def test_stats_validates_the_window(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    client = await stack.login()
    assert (await client.get("/api/stats?hours=0")).status_code == 422
    assert (await client.get("/api/stats?hours=100000")).status_code == 422


async def test_status_requires_login_and_shows_models(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user()
    assert (await stack.anonymous().get("/api/status")).status_code == 401
    client = await stack.login()
    status = (await client.get("/api/status")).json()
    assert set(status["models"]) == {"a", "b", "c"}
    assert set(status["gpus"]) == {"0", "1"}
