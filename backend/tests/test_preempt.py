"""PREEMPT_AFTER_S: a high-priority request that waited long enough stops a lower-priority one."""

import asyncio
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import ValidationError

from llm_manager.core.models_config import EngineConfig
from tests.conftest import PORTS, StackFactory, until_busy
from tests.fakes import FakeVLLM

LONG = 5.0  # a request that would otherwise hold the GPU for far longer than any test waits


def kinds(stack: object) -> list[str]:
    return [e.kind for e in stack.container.manager.events]  # type: ignore[attr-defined]


def sleep_detail(stack: object, model: str) -> str:
    events = stack.container.manager.events  # type: ignore[attr-defined]
    return str([e.detail for e in events if e.kind == "sleep" and e.model == model][-1])


async def test_a_waiting_priority_request_stops_the_running_one_after_the_set_time(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack(priorities={"a": 5}, preempt_after_s=0.4, min_awake_s=30)
    token = await stack.api_key()
    running = asyncio.create_task(stack.chat(token, "b", work_s=LONG))
    await until_busy(stack, "b")
    started = time.monotonic()
    served = await stack.chat(token, "a")
    waited = time.monotonic() - started

    assert served.status_code == 200
    assert 0.3 <= waited < 3  # it waited the set time, then took the GPU: not the whole LONG
    stopped = await running
    assert stopped.status_code == 503
    assert "higher-priority" in stopped.text
    assert int(stopped.headers["retry-after"]) > 0
    assert "preempt" in kinds(stack)
    assert stack.fakes["b"].active == 0
    assert stack.ledger.violations == []  # b was not put to sleep while it was still working
    assert (await stack.chat(token, "b")).status_code == 200  # b serves again afterwards


async def test_nothing_is_stopped_unless_the_setting_is_on(make_stack: StackFactory) -> None:
    stack = await make_stack(priorities={"a": 5}, queue_timeout_s=1.0, min_awake_s=30)
    token = await stack.api_key()
    running = asyncio.create_task(stack.chat(token, "b", work_s=2.0))
    await until_busy(stack, "b")
    timed_out = await stack.chat(token, "a")

    assert timed_out.status_code == 503
    assert "timed out" in timed_out.text
    assert (await running).status_code == 200  # b finished what it was doing
    assert "preempt" not in kinds(stack)


async def test_a_request_of_equal_priority_is_never_stopped(make_stack: StackFactory) -> None:
    stack = await make_stack(preempt_after_s=0.3)
    token = await stack.api_key()
    running = asyncio.create_task(stack.chat(token, "b", work_s=1.2))
    await until_busy(stack, "b")
    waiting = await stack.chat(token, "a")

    assert (await running).status_code == 200
    assert waiting.status_code == 200  # it waited its turn instead
    assert "preempt" not in kinds(stack)
    assert stack.ledger.violations == []


async def test_a_busy_higher_priority_model_is_never_stopped(make_stack: StackFactory) -> None:
    stack = await make_stack(priorities={"b": 5}, preempt_after_s=0.3)
    token = await stack.api_key()
    running = asyncio.create_task(stack.chat(token, "b", work_s=1.2))
    await until_busy(stack, "b")
    waiting = await stack.chat(token, "a")

    assert (await running).status_code == 200
    assert waiting.status_code == 200
    assert "preempt" not in kinds(stack)
    assert stack.ledger.violations == []


class SlowStream(httpx.AsyncByteStream):
    """An answer that trickles out for seconds, like a long generation (the in-memory fake
    transport hands back whole responses, so a real stream needs its own)."""

    def __init__(self, fake: FakeVLLM) -> None:
        self.fake = fake

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.fake.active += 1
        try:
            for i in range(3):
                yield f"data: chunk{i}\n\n".encode()
                await asyncio.sleep(1.0)
            yield b"data: [DONE]\n\n"
        finally:
            self.fake.active -= 1


async def test_a_streaming_answer_ends_with_an_error_event(make_stack: StackFactory) -> None:
    stack = await make_stack(priorities={"a": 5}, preempt_after_s=0.4, min_awake_s=30)
    token = await stack.api_key()
    real = stack.dispatch.handle_async_request

    async def route(request: httpx.Request) -> httpx.Response:
        if request.url.port == PORTS["b"] and request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=SlowStream(stack.fakes["b"]),
            )
        return await real(request)

    stack.dispatch.handle_async_request = route  # type: ignore[method-assign]

    async def read_stream() -> str:
        async with stack.anonymous().stream(
            "POST",
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}"},
            json={"model": "b", "messages": [], "stream": True},
        ) as response:
            assert response.status_code == 200  # already streaming when it was stopped
            return "".join([part async for part in response.aiter_text()])

    reading = asyncio.create_task(read_stream())
    await asyncio.sleep(0.2)
    started = time.monotonic()
    assert (await stack.chat(token, "a")).status_code == 200
    assert time.monotonic() - started < 2.5  # not the 3 s the stream would have taken
    text = await reading

    assert "chunk0" in text  # it had started
    assert "higher-priority" in text  # and ends with a readable reason
    assert "chunk2" not in text
    assert stack.fakes["b"].active == 0
    assert stack.ledger.violations == []


def test_the_setting_must_be_smaller_than_the_queue_timeout() -> None:
    with pytest.raises(ValidationError, match="smaller than queue_timeout_s"):
        EngineConfig(queue_timeout_s=60, preempt_after_s=60)
    assert EngineConfig(queue_timeout_s=60, preempt_after_s=30).preempt_after_s == 30
    assert EngineConfig().preempt_after_s is None


async def test_the_victim_is_only_slept_once_its_engine_has_really_stopped(
    make_stack: StackFactory,
) -> None:
    """vLLM keeps working on an aborted request for a moment; sleeping then kills the engine."""
    stack = await make_stack(priorities={"a": 5}, preempt_after_s=0.3, min_awake_s=30)
    token = await stack.api_key()
    running = asyncio.create_task(stack.chat(token, "b", work_s=LONG))
    await until_busy(stack, "b")
    stack.fakes["b"].abort_lag_s = 1.2  # still working on the request 1.2 s after the stop
    started = time.monotonic()
    served = await stack.chat(token, "a")
    assert served.status_code == 200
    assert time.monotonic() - started >= 1.0  # a waited for b's engine, not just for the cancel
    assert (await running).status_code == 503
    assert stack.ledger.violations == []
    assert "engine quiet after" in sleep_detail(stack, "b")  # the history says how it was proven


async def test_a_model_whose_engine_never_goes_quiet_is_not_slept(
    make_stack: StackFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cancel never reached vLLM: the request keeps generating, so the GPU is not freed."""
    monkeypatch.setattr("llm_manager.engine.manager._QUIET_LIMIT_S", 0.6)
    stack = await make_stack(
        priorities={"a": 5}, preempt_after_s=0.3, min_awake_s=30, queue_timeout_s=2
    )
    token = await stack.api_key()
    running = asyncio.create_task(stack.chat(token, "b", work_s=LONG))
    await until_busy(stack, "b")
    stack.fakes["b"].abort_lag_s = 60
    assert (await stack.chat(token, "a")).status_code == 503  # could not free the GPU: retry later
    await running
    assert "sleep_failed" in kinds(stack)
    assert stack.ledger.violations == []  # b was never put to sleep under a working engine


@pytest.mark.parametrize("counters", ["missing", "frozen"])
async def test_without_counters_a_fixed_pause_is_used(
    make_stack: StackFactory, monkeypatch: pytest.MonkeyPatch, counters: str
) -> None:
    """No /metrics (or none that move while busy): all that is left is a fixed pause."""
    monkeypatch.setattr("llm_manager.engine.manager._ABORT_SETTLE_S", 1.0)
    stack = await make_stack(priorities={"a": 5}, preempt_after_s=0.3, min_awake_s=30)
    stack.fakes["b"].counters = counters
    stack.fakes["b"].abort_lag_s = 0.8  # vLLM drops the aborted request 0.8 s after the cancel
    token = await stack.api_key()
    running = asyncio.create_task(stack.chat(token, "b", work_s=LONG))
    await until_busy(stack, "b")
    started = time.monotonic()
    assert (await stack.chat(token, "a")).status_code == 200
    assert time.monotonic() - started >= 0.9  # the pause, not a quiet engine
    assert (await running).status_code == 503
    assert stack.ledger.violations == []
    assert "fixed pause" in sleep_detail(stack, "b")


async def test_a_model_is_slept_without_delay_when_nothing_was_cancelled(
    make_stack: StackFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("llm_manager.engine.manager._ABORT_SETTLE_S", 5.0)
    stack = await make_stack(min_awake_s=0.1)
    token = await stack.api_key()
    assert (await stack.chat(token, "b")).status_code == 200
    started = time.monotonic()
    assert (await stack.chat(token, "a")).status_code == 200  # swap: b finished normally
    assert time.monotonic() - started < 2.0
    assert stack.ledger.violations == []
