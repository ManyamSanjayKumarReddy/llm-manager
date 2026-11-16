"""The wake/sleep engine, exercised through the real HTTP API."""

import asyncio
import random
import time

from tests.conftest import StackFactory, model_state


async def test_startup_puts_everything_to_sleep(make_stack: StackFactory) -> None:
    stack = await make_stack()
    assert {model_state(stack, n) for n in "abc"} == {"asleep"}
    # "d" is a running container nobody registered: the router must leave it alone
    assert stack.ledger.awake == {"d"}


async def test_wake_on_demand_then_idle_sleep(make_stack: StackFactory) -> None:
    stack = await make_stack(idle_minutes=0.005)  # 0.3 seconds
    token = await stack.api_key()
    response = await stack.chat(token, "a")
    assert response.status_code == 200
    assert response.json()["served_by"] == "a"
    assert model_state(stack, "a") == "awake"
    await asyncio.sleep(0.8)
    assert model_state(stack, "a") == "asleep"
    assert stack.ledger.violations == []


async def test_served_name_is_sent_to_the_backend(make_stack: StackFactory) -> None:
    stack = await make_stack()
    token = await stack.api_key()
    await stack.chat(token, "a")
    assert stack.fakes["a"].last_model == "org/a"
    assert (await stack.chat(token, "org/a")).status_code == 200  # vLLM's own name also works


async def test_swap_waits_for_running_requests(make_stack: StackFactory) -> None:
    stack = await make_stack()
    token = await stack.api_key()
    slow = asyncio.create_task(stack.chat(token, "a", work_s=0.5))
    await asyncio.sleep(0.1)
    started = time.monotonic()
    response = await stack.chat(token, "b")  # shares GPU 0 with a: must wait for it
    assert response.status_code == 200
    assert response.json()["served_by"] == "b"
    assert time.monotonic() - started >= 0.3
    assert (await slow).status_code == 200
    assert stack.ledger.violations == []


async def test_models_on_different_gpus_stay_awake_together(make_stack: StackFactory) -> None:
    stack = await make_stack()
    token = await stack.api_key()
    assert (await stack.chat(token, "b")).status_code == 200
    assert (await stack.chat(token, "c")).status_code == 200
    assert model_state(stack, "b") == model_state(stack, "c") == "awake"
    assert stack.ledger.violations == []


async def test_big_model_evicts_both_small_ones(make_stack: StackFactory) -> None:
    stack = await make_stack()
    token = await stack.api_key()
    await stack.chat(token, "b")
    await stack.chat(token, "c")
    assert (await stack.chat(token, "a")).status_code == 200
    assert [model_state(stack, n) for n in "abc"] == ["awake", "asleep", "asleep"]
    assert stack.ledger.violations == []


async def test_streaming_is_passed_through(make_stack: StackFactory) -> None:
    stack = await make_stack()
    response = await stack.chat(await stack.api_key(), "a", stream=True)
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "chunk0" in response.text
    assert "[DONE]" in response.text


async def test_random_traffic_never_breaks_a_rule(make_stack: StackFactory) -> None:
    stack = await make_stack(idle_minutes=0.003, min_awake_s=0.05)
    token = await stack.api_key()
    rng = random.Random(7)

    async def one() -> int:
        await asyncio.sleep(rng.random())
        response = await stack.chat(token, rng.choice("abc"), work_s=rng.random() * 0.05)
        return response.status_code

    codes = await asyncio.gather(*(one() for _ in range(80)))
    assert codes.count(200) == 80
    assert stack.ledger.violations == []
    assert all(m.inflight == 0 for m in stack.container.manager.models.values())


async def test_a_waiting_model_is_not_starved(make_stack: StackFactory) -> None:
    stack = await make_stack(min_awake_s=0.2)
    token = await stack.api_key()
    stop = False

    async def hammer_b() -> None:  # a constant stream of requests keeps b busy
        while not stop:
            await stack.chat(token, "b", work_s=0.05)

    hammers = [asyncio.create_task(hammer_b()) for _ in range(4)]
    await asyncio.sleep(0.3)
    started = time.monotonic()
    response = await stack.chat(token, "a")  # needs both GPUs while b is hammered
    waited = time.monotonic() - started
    stop = True
    await asyncio.gather(*hammers)
    assert response.status_code == 200
    assert waited < 3.0
    assert stack.ledger.violations == []


async def test_queue_timeout_gives_503_with_retry_after(make_stack: StackFactory) -> None:
    stack = await make_stack(queue_timeout_s=0.3)
    token = await stack.api_key()
    slow = asyncio.create_task(stack.chat(token, "a", work_s=1.5))
    await asyncio.sleep(0.1)
    response = await stack.chat(token, "b")
    assert response.status_code == 503
    assert "retry-after" in response.headers
    assert response.json()["error"]["code"] == "model_unavailable"  # OpenAI-style error body
    assert stack.container.manager.models["b"].rejected == 1
    assert (await slow).status_code == 200


async def test_a_failed_wake_gives_503_and_then_recovers(make_stack: StackFactory) -> None:
    stack = await make_stack()
    token = await stack.api_key()
    stack.fakes["b"].fail_wake = True
    assert (await stack.chat(token, "b")).status_code == 503
    assert model_state(stack, "b") != "waking"
    stack.fakes["b"].fail_wake = False
    assert (await stack.chat(token, "b")).status_code == 200


async def test_backend_errors_are_counted_and_passed_through(make_stack: StackFactory) -> None:
    stack = await make_stack()
    response = await stack.chat(await stack.api_key(), "a", fail=True)
    assert response.status_code == 500  # the model's own error is not rewritten
    model = stack.container.manager.models["a"]
    assert (model.requests, model.errors) == (1, 1)


async def test_requests_wait_for_the_startup_check_instead_of_failing(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    manager = stack.container.manager
    token = await stack.api_key()
    stack.fakes["a"].sleep_s = 0.4  # a slow startup check: a is awake and must be put to sleep
    stack.fakes["a"].sleeping = False
    stack.ledger.wake("a")
    manager._starting = True  # as right after a restart: the app is up, the check is running
    request = asyncio.create_task(stack.chat(token, "a"))
    await asyncio.sleep(0.15)
    assert not request.done()  # waiting, not rejected with "backend is down"
    startup = asyncio.create_task(manager.startup())
    response = await request
    await startup
    assert response.status_code == 200
    assert stack.ledger.violations == []
