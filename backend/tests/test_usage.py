"""Token usage: read from what passes through, added up per day, key and model."""

import httpx

from llm_manager.core.usage import JsonTail, SseUsage, usage_from_json_tail, wants_stream_usage
from tests.conftest import Stack, StackFactory, eventually
from tests.fakes import USAGE


async def admin(stack: Stack) -> httpx.AsyncClient:
    await stack.create_user()
    return await stack.login()


# ----------------------------------------------------------------- reading usage (pure)
def test_usage_is_read_from_the_end_of_a_json_reply() -> None:
    reply = (
        b'{"id": "x", "choices": [{"text": "hi"}], '
        b'"usage": {"prompt_tokens": 7, "completion_tokens": 5}}'
    )
    found = usage_from_json_tail(reply)
    assert found is not None
    assert (found.prompt_tokens, found.completion_tokens, found.total_tokens) == (7, 5, 12)
    assert usage_from_json_tail(b'{"choices": []}') is None
    assert usage_from_json_tail(b'{"usage": "nope"}') is None
    embeddings = usage_from_json_tail(
        b'{"data": [], "usage": {"prompt_tokens": 3, "total_tokens": 3}}'
    )
    assert embeddings is not None
    assert (embeddings.prompt_tokens, embeddings.completion_tokens) == (3, 0)


def test_only_the_tail_of_a_huge_reply_is_kept() -> None:
    tail = JsonTail()
    tail.feed(
        b'{"data": "'
        + b"x" * 1_000_000
        + b'", "usage": {"prompt_tokens": 9, "completion_tokens": 0}}'
    )
    found = tail.usage()
    assert found is not None
    assert found.prompt_tokens == 9


def test_usage_is_asked_for_on_streams_only() -> None:
    body: dict[str, object] = {"stream": True}
    assert wants_stream_usage("chat/completions", body) is False  # we asked, so hide it again
    assert body["stream_options"] == {"include_usage": True}
    keep: dict[str, object] = {"stream": True, "stream_options": {"include_usage": True}}
    assert wants_stream_usage("completions", keep) is True  # the client wants it itself
    other: dict[str, object] = {"stream": True, "stream_options": {"continuous_usage_stats": True}}
    assert wants_stream_usage("chat/completions", other) is False
    assert other["stream_options"] == {"continuous_usage_stats": True, "include_usage": True}
    plain: dict[str, object] = {}
    assert wants_stream_usage("chat/completions", plain) is None
    assert plain == {}
    assert wants_stream_usage("embeddings", {"stream": True}) is None
    assert wants_stream_usage("chat/completions", {"stream": True, "stream_options": 5}) is None


STREAM = (
    b'data: {"choices": [{"delta": {"content": "a"}}]}\n\n'
    b'data: {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2}}\n\n'
    b"data: [DONE]\n\n"
)


def _run(tap: SseUsage, pieces: list[bytes]) -> bytes:
    return b"".join(tap.feed(p) for p in pieces) + tap.finish()


def test_the_usage_event_is_hidden_from_clients_that_did_not_ask() -> None:
    for size in (len(STREAM), 7, 1):  # however the network cuts the stream
        tap = SseUsage(strip=True)
        pieces = [STREAM[i : i + size] for i in range(0, len(STREAM), size)]
        sent = _run(tap, pieces)
        assert sent == (b'data: {"choices": [{"delta": {"content": "a"}}]}\n\ndata: [DONE]\n\n'), (
            size
        )
        assert tap.usage is not None
        assert (tap.usage.prompt_tokens, tap.usage.completion_tokens) == (4, 2)


def test_the_usage_event_is_kept_for_clients_that_asked() -> None:
    tap = SseUsage(strip=False)
    assert _run(tap, [STREAM[:30], STREAM[30:]]) == STREAM  # byte for byte
    assert tap.usage is not None
    assert tap.usage.completion_tokens == 2


# ---------------------------------------------------------------------- end to end
async def test_tokens_are_counted_per_key_and_model(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    token = await stack.api_key("alpha")
    other = await stack.api_key("beta")
    for _ in range(3):
        assert (await stack.chat(token, "b")).status_code == 200
    assert (await stack.chat(token, "c")).status_code == 200
    assert (await stack.chat(other, "b")).status_code == 200

    async def counted() -> bool:
        body = (await client.get("/api/usage?days=7")).json()
        return body["totals"]["requests"] == 5

    await eventually(counted)
    body = (await client.get("/api/usage?days=7")).json()
    assert body["totals"] == {
        "requests": 5,
        "errors": 0,
        "prompt_tokens": 5 * USAGE["prompt_tokens"],
        "completion_tokens": 5 * USAGE["completion_tokens"],
        "total_tokens": 5 * USAGE["total_tokens"],
    }
    keys = {k["label"]: k for k in body["keys"]}
    assert keys["alpha"]["requests"] == 4
    assert keys["alpha"]["total_tokens"] == 4 * USAGE["total_tokens"]
    assert keys["beta"]["requests"] == 1
    assert body["keys"][0]["label"] == "alpha"  # biggest user first
    models = {m["model"]: m["requests"] for m in body["models"]}
    assert models == {"b": 4, "c": 1}
    assert len(body["daily"]) == 7
    assert body["daily"][-1]["requests"] == 5  # today
    assert sum(d["requests"] for d in body["daily"][:-1]) == 0


async def test_unused_keys_are_listed_with_zeros(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await stack.api_key("quiet")
    keys = (await client.get("/api/usage")).json()["keys"]
    assert [(k["label"], k["requests"], k["total_tokens"]) for k in keys] == [("quiet", 0, 0)]


async def test_one_keys_usage(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    token = await stack.api_key("alpha")
    other = await stack.api_key("beta")
    await stack.chat(token, "b")
    await stack.chat(other, "c")

    async def both() -> bool:
        return (await client.get("/api/usage")).json()["totals"]["requests"] == 2

    await eventually(both)
    keys = (await client.get("/api/usage")).json()["keys"]
    alpha = next(k for k in keys if k["label"] == "alpha")
    detail = (await client.get(f"/api/usage/keys/{alpha['id']}?days=3")).json()
    assert detail["key"]["requests"] == 1
    assert [m["model"] for m in detail["models"]] == ["b"]
    assert len(detail["daily"]) == 3
    missing = await client.get("/api/usage/keys/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


async def test_errors_are_counted_and_cost_no_tokens(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    token = await stack.api_key("alpha")
    assert (await stack.chat(token, "b", fail=True)).status_code == 500

    async def seen() -> bool:
        return (await client.get("/api/usage")).json()["totals"]["requests"] == 1

    await eventually(seen)
    totals = (await client.get("/api/usage")).json()["totals"]
    assert (totals["errors"], totals["total_tokens"]) == (1, 0)


async def test_streams_are_counted_and_the_client_sees_no_extra_event(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    client = await admin(stack)
    token = await stack.api_key("alpha")
    plain = await stack.chat(token, "b", stream=True)
    assert "usage" not in plain.text  # we asked vLLM for it, but the client did not
    assert plain.text.rstrip().endswith("data: [DONE]")
    assert stack.fakes["b"].last_body["stream_options"] == {"include_usage": True}
    asked = await stack.chat(token, "b", stream=True, stream_options={"include_usage": True})
    assert '"usage"' in asked.text  # this client wanted it

    async def counted() -> bool:
        return (await client.get("/api/usage")).json()["totals"]["requests"] == 2

    await eventually(counted)
    totals = (await client.get("/api/usage")).json()["totals"]
    assert totals["prompt_tokens"] == 2 * USAGE["prompt_tokens"]
    assert totals["completion_tokens"] == 2 * USAGE["completion_tokens"]


async def test_only_admins_see_usage(make_stack: StackFactory) -> None:
    stack = await make_stack()
    from llm_manager.db.models import Role

    await stack.create_user("viewer1", Role.VIEWER, "a-long-passphrase")
    viewer = await stack.login("viewer1", "a-long-passphrase")
    assert (await viewer.get("/api/usage")).status_code == 403
    assert (await stack.anonymous().get("/api/usage")).status_code == 401
