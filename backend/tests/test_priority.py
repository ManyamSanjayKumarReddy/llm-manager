"""Priority decides who goes first when models that share a GPU compete; idle models sleep."""

import asyncio
import time

import httpx

from llm_manager.core.models_config import EngineConfig, ModelSpec
from llm_manager.engine import Manager
from llm_manager.engine.backend import VllmBackend
from tests.conftest import Stack, StackFactory, eventually, model_state
from tests.fakes import Dispatch, FakeVLLM, Ledger


async def run(stack: Stack, token: str, steps: list[tuple[float, str, str, float]]) -> list[str]:
    """Start requests at the given times; return the labels in the order they finished."""
    done: list[str] = []

    async def call(label: str, model: str, work_s: float) -> None:
        response = await stack.chat(token, model, work_s=work_s)
        assert response.status_code == 200, (label, response.text)
        done.append(label)

    tasks = []
    started = time.monotonic()
    for at, label, model, work_s in steps:
        await asyncio.sleep(max(0.0, at - (time.monotonic() - started)))
        tasks.append(asyncio.create_task(call(label, model, work_s)))
    await asyncio.gather(*tasks)
    return done


# b (GPU 0) is busy; a (GPUs 0+1) wants in; then b gets another request.
ORDER = [(0.0, "b1", "b", 0.6), (0.15, "a", "a", 0.05), (0.3, "b2", "b", 0.05)]


async def test_equal_priority_keeps_taking_turns(make_stack: StackFactory) -> None:
    stack = await make_stack(min_awake_s=30)  # b's turn has not run out, so b keeps going
    done = await run(stack, await stack.api_key(), ORDER)
    assert done[-1] == "a"  # the waiting model only gets in after b is done
    assert stack.ledger.violations == []


async def test_a_waiting_higher_priority_model_makes_the_awake_one_yield_at_once(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack(min_awake_s=30, priorities={"a": 5})
    done = await run(stack, await stack.api_key(), ORDER)
    assert done.index("a") < done.index("b2")  # b finished what it was doing, then handed over
    assert done[0] == "b1"  # but nothing running was cut short
    assert stack.ledger.violations == []


async def test_a_busy_higher_priority_model_is_not_interrupted(make_stack: StackFactory) -> None:
    stack = await make_stack(min_awake_s=0.1, priorities={"a": 5})
    done = await run(
        stack,
        await stack.api_key(),
        [(0.0, "a1", "a", 0.6), (0.2, "b", "b", 0.05), (0.4, "a2", "a", 0.05)],
    )
    # b has waited longer than min_awake_s, yet the more important model keeps serving
    assert done.index("a2") < done.index("b")
    assert done[-1] == "b"  # b still gets in once a is idle: it is not starved
    assert stack.ledger.violations == []


async def test_a_lower_priority_model_waits_for_a_higher_one_to_cool_down(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack(priority_hold_s=0.6, priorities={"a": 5})
    token = await stack.api_key()
    await stack.chat(token, "a")  # a just served a request
    started = time.monotonic()
    assert (await stack.chat(token, "b")).status_code == 200
    assert time.monotonic() - started >= 0.5  # b waited out a's cool-down, not an instant swap
    assert stack.ledger.violations == []


async def test_equal_priority_swaps_without_a_cool_down(make_stack: StackFactory) -> None:
    stack = await make_stack(priority_hold_s=0.6)
    token = await stack.api_key()
    await stack.chat(token, "a")
    started = time.monotonic()
    assert (await stack.chat(token, "b")).status_code == 200
    assert time.monotonic() - started < 0.5


class Trio:
    """Three models on the same GPU, driven directly through the scheduler."""

    def __init__(self, priorities: dict[str, int]) -> None:
        self.ledger = Ledger({n: frozenset({0}) for n in "xyz"})
        self.fakes = {n: FakeVLLM(n, self.ledger) for n in "xyz"}
        self.ledger.violations.clear()
        ports = {"x": 9101, "y": 9102, "z": 9103}
        self.http = httpx.AsyncClient(
            transport=Dispatch({ports[n]: f.app for n, f in self.fakes.items()})
        )
        models = {
            n: ModelSpec(
                url=f"http://127.0.0.1:{ports[n]}", gpus=frozenset({0}), priority=priorities[n]
            )
            for n in "xyz"
        }
        config = EngineConfig(
            min_awake_s=0.1,
            priority_hold_s=0.1,
            queue_timeout_s=10,
            reaper_interval_s=0.05,
        )
        backend = VllmBackend(self.http, sleep_level=1, sleep_timeout_s=5, wake_timeout_s=5)
        self.manager = Manager(config, backend, models)

    async def serve_order(self) -> list[str]:
        """z is busy; x asks first, then y; return who gets served first once z is done."""
        await self.manager.startup()
        z = await self.manager.acquire("z")
        order: list[str] = []

        async def go(name: str) -> None:
            model = await self.manager.acquire(name)
            order.append(name)
            await asyncio.sleep(0.1)
            self.manager.release(model)

        tasks = [asyncio.create_task(go("x"))]
        await asyncio.sleep(0.1)
        tasks.append(asyncio.create_task(go("y")))
        await asyncio.sleep(0.1)
        self.manager.release(z)
        await asyncio.gather(*tasks)
        await self.http.aclose()
        await self.manager.aclose()
        assert self.ledger.violations == []
        return order


async def test_first_come_first_served_when_priorities_are_equal() -> None:
    assert await Trio({"x": 0, "y": 0, "z": 0}).serve_order() == ["x", "y"]


async def test_the_highest_priority_waiter_goes_first() -> None:
    assert await Trio({"x": 0, "y": 5, "z": 0}).serve_order() == ["y", "x"]


async def test_priority_order_follows_the_numbers_not_arrival() -> None:
    assert await Trio({"x": 3, "y": 2, "z": 0}).serve_order() == ["x", "y"]
    assert await Trio({"x": 2, "y": 3, "z": 0}).serve_order() == ["y", "x"]


async def test_idle_models_go_to_sleep_whatever_their_priority(make_stack: StackFactory) -> None:
    # b and c use different GPUs, so both can be awake at once
    stack = await make_stack(idle_minutes=0.005, priorities={"b": 9, "c": 0})
    token = await stack.api_key()
    await stack.chat(token, "b")
    await stack.chat(token, "c")
    assert model_state(stack, "b") == model_state(stack, "c") == "awake"

    async def both_asleep() -> bool:
        return model_state(stack, "b") == model_state(stack, "c") == "asleep"

    await eventually(both_asleep, timeout_s=5)  # nobody asked for them: neither stays loaded
    assert stack.fakes["b"].sleeping
    assert stack.fakes["c"].sleeping


async def test_a_model_that_is_used_does_not_sleep(make_stack: StackFactory) -> None:
    stack = await make_stack(idle_minutes=0.01, priorities={"b": 0})
    token = await stack.api_key()
    for _ in range(6):
        await stack.chat(token, "b")
        await asyncio.sleep(0.2)  # always more recent than the idle limit
    assert model_state(stack, "b") == "awake"


async def test_no_requests_means_everything_is_asleep(make_stack: StackFactory) -> None:
    stack = await make_stack()
    assert {model_state(stack, n) for n in ("a", "b", "c")} == {"asleep"}
