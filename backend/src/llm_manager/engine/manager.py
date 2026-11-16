"""Decides which vLLM model is awake, and wakes/sleeps them on demand.

The whole design in six rules:

1. A model is ASLEEP (weights in CPU RAM, GPU almost empty) or AWAKE (serving).
2. Two models that share a GPU are never AWAKE together.
3. A request needs its model AWAKE; if it is not, the request waits while the conflicting
   model(s) are put to sleep and the one it needs is woken.
4. A model is never put to sleep while it has requests running.
5. A model that waited gets a turn: after ``min_awake_s`` the awake model stops taking
   new requests so the waiting one can swap in (no starvation).
6. Every state change happens under one lock, so two requests can never put each
   other's model to sleep.
7. Priority decides who goes first when models that share a GPU compete: a waiting model
   with a higher priority makes the awake one stop taking new requests at once, and when
   several models wait the highest priority swaps in first. A lower-priority model never
   interrupts a higher-priority one that is serving (or served within ``priority_hold_s``).
   Equal priorities take turns as in rule 5.
8. Optional (``preempt_after_s``): rule 4 and 7 keep running requests safe, but a request that
   has waited this long for a model with a HIGHER priority than the one in its way asks that
   model's running requests to stop (the proxy cancels them with a 503), then swaps in. Equal
   or higher priorities are never stopped.
"""

import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from llm_manager.core.errors import (
    InvalidInputError,
    NotFoundError,
    UnavailableError,
    UnknownModelError,
)
from llm_manager.core.models_config import EngineConfig, ModelSpec
from llm_manager.engine.backend import BackendError, VllmBackend
from llm_manager.engine.states import HOLDS_GPU, ModelRuntime, State
from llm_manager.schemas.status import EventOut, GpuHolder, ModelStatus, StatusOut

log = logging.getLogger(__name__)

_RECHECK_INTERVAL_S = 1.0  # waiters re-evaluate at least this often (timers expire silently)
_ABORT_SETTLE_S = 3.0  # least time between a cancelled request and /sleep (see _drain)
_CALIBRATE_GAP_S = 0.5  # before a stop: gap between the two counter readings
_QUIET_S = 2.0  # the engine counts as stopped once it has processed no tokens for this long
_QUIET_LIMIT_S = 20.0  # ... and a model still working after this long is left alone
_ASLEEP_CHECK_S = 1.0  # a sleeping container is asked whether it is still there at most this often
_MIN_REPORTED_WAIT_S = 0.05  # shorter waits are not counted as "had to wait"
_EVENT_HISTORY = 200
_RETRY_AFTER_QUEUE_S = 10
_RETRY_AFTER_DOWN_S = 10
_RETRY_AFTER_FAILED_SWAP_S = 15


class _Verdict(Enum):
    GO = auto()  # model is ready: take a slot
    WAIT = auto()  # not yet: wait and re-check


@dataclass(frozen=True)
class _Swap:
    """Wake ``target`` after putting ``to_sleep`` (models in its way) to sleep."""

    target: ModelRuntime
    to_sleep: list[ModelRuntime]


class Manager:
    """Owns the state of every model and performs wake/sleep transitions."""

    def __init__(
        self,
        config: EngineConfig,
        backend: VllmBackend,
        models: dict[str, ModelSpec] | None = None,
        *,
        starting: bool = False,
    ) -> None:
        self.config = config
        self._backend = backend
        self.models = {name: ModelRuntime(name, spec) for name, spec in (models or {}).items()}
        self._cond = asyncio.Condition()
        # True until ``startup`` has found out where every container is. Requests wait for it.
        self._starting = starting
        self._tasks: set[asyncio.Task[Any]] = set()
        self.started_at = time.time()
        self.events: deque[EventOut] = deque(maxlen=_EVENT_HISTORY)  # newest last
        self.event_sink: Callable[[EventOut], None] | None = None  # persists events

    # ------------------------------------------------------------------ helpers
    def resolve(self, name: str) -> ModelRuntime:
        """Find a model by its configured name or by vLLM's own served name."""
        if name in self.models:
            return self.models[name]
        for model in self.models.values():
            if model.served_name == name:
                return model
        raise UnknownModelError(name)

    def _event(self, model: ModelRuntime | None, kind: str, detail: str = "") -> None:
        event = EventOut(
            t=time.time(), model=model.name if model else None, kind=kind, detail=detail
        )
        self.events.append(event)
        if self.event_sink is not None:
            try:
                self.event_sink(event)
            except Exception:
                log.exception("event sink failed")

    def _spawn[T](self, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        """Run a coroutine as a tracked task (kept referenced until it finishes)."""
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)

        def _done(finished: asyncio.Task[Any]) -> None:
            self._tasks.discard(finished)
            if not finished.cancelled():
                finished.exception()  # mark retrieved, avoids "never retrieved" warnings

        task.add_done_callback(_done)
        return task

    async def _set_state(
        self, model: ModelRuntime, state: State, *, take_slot: bool = False
    ) -> None:
        async with self._cond:
            model.state = state
            if state is State.AWAKE:
                model.awake_since = model.last_used = time.monotonic()
            if state in (State.AWAKE, State.ASLEEP):
                model.preempt_event.clear()  # a stop request never outlives the swap it served
                model.stop_requested = False
            if take_slot:  # hand the waker its slot before anyone can put the model to sleep
                model.inflight += 1
            self._cond.notify_all()

    async def _notify(self) -> None:
        async with self._cond:
            self._cond.notify_all()

    # -------------------------------------------------------------- transitions
    async def _probe(self, model: ModelRuntime) -> State:
        """Ask the container what state it is really in."""
        try:
            asleep = await self._backend.is_sleeping(model.spec)
        except BackendError as exc:
            log.warning("model %s unreachable: %s", model.name, exc)
            return State.DOWN
        return State.ASLEEP if asleep else State.AWAKE

    async def _go_to_sleep(self, model: ModelRuntime, reason: str) -> bool:
        """Sleep a model already marked SLEEPING. Returns True if it is now asleep."""
        try:
            drained = await self._drain(model)
            await self._backend.sleep(model.spec)
        except BackendError as exc:
            log.exception("sleeping %s failed", model.name)
            self._event(model, "sleep_failed", str(exc))
            new_state = await self._probe(model)
        else:
            new_state = State.ASLEEP
            model.sleeps += 1
            model.aborted_at = float("-inf")
            self._event(model, "sleep", f"{reason} ({drained})" if drained else reason)
            log.info("model %s -> asleep (%s)", model.name, reason)
        await self._set_state(model, new_state)
        return new_state is State.ASLEEP

    async def _drain(self, model: ModelRuntime) -> str:
        """Make sure vLLM has really dropped cancelled requests before its GPU memory is freed.

        A /sleep that lands while the engine still has such a request frees the weights under
        it, and the next step kills the engine ("illegal memory access"). vLLM says nothing
        reliable about that (its "running" gauge keeps the last value or stays 0), but its token
        counters only move while it works. So: wait until they have been still for a while.
        Raises BackendError, and the model is not slept, if it is still working after the limit.
        Returns a short description for the history ("" if nothing had been cancelled).
        """
        if model.aborted_at == float("-inf"):
            return ""
        if model.counters_work:
            waited = await self._backend.wait_until_quiet(
                model.spec, quiet_s=_QUIET_S, limit_s=_QUIET_LIMIT_S
            )
            how = f"engine quiet after {waited:.1f}s"
        else:  # no usable counters: only a fixed pause is left
            how = "fixed pause, engine activity unknown"
        if (settle := model.aborted_at + _ABORT_SETTLE_S - time.monotonic()) > 0:
            await asyncio.sleep(settle)
        return how

    async def _wake_and_verify(self, model: ModelRuntime) -> None:
        """Call ``/wake_up`` and confirm the container no longer reports sleeping."""
        await self._backend.wake(model.spec)
        if await self._backend.is_sleeping(model.spec):
            raise BackendError("still reports sleeping after wake_up")

    async def _wake(self, model: ModelRuntime, *, take_slot: bool) -> bool:
        """Wake a model already marked WAKING. Returns True if it is now awake."""
        started = time.monotonic()
        try:
            await self._wake_and_verify(model)
        except BackendError as exc:
            log.exception("waking %s failed", model.name)
            self._event(model, "wake_failed", str(exc))
            new_state = await self._probe(model)
        else:
            new_state = State.AWAKE
        await self._set_state(model, new_state, take_slot=take_slot and new_state is State.AWAKE)
        if new_state is State.AWAKE:
            elapsed = time.monotonic() - started
            model.wakes += 1
            model.wake_total_s += elapsed
            model.last_wake_s = elapsed
            self._event(model, "woke", f"{elapsed:.2f}s")
            log.info("model %s -> awake in %.2fs", model.name, elapsed)
        return new_state is State.AWAKE

    async def _run_swap(self, swap: _Swap) -> ModelRuntime:
        target = swap.target
        slept = await asyncio.gather(
            *(self._go_to_sleep(o, f"swap for {target.name}") for o in swap.to_sleep)
        )
        if not all(slept):
            await self._set_state(target, State.ASLEEP)
            raise UnavailableError(
                f"could not free the GPU for {target.name}", _RETRY_AFTER_FAILED_SWAP_S
            )
        if not await self._wake(target, take_slot=True):
            raise UnavailableError(
                f"model {target.name} failed to wake", _RETRY_AFTER_FAILED_SWAP_S
            )
        return target

    # ---------------------------------------------------------------- decisions
    def _decide(self, model: ModelRuntime, waited_s: float = 0.0) -> _Verdict | _Swap:
        """Decide what a request for ``model`` must do. Called with the lock held."""
        now = time.monotonic()
        if self._starting:
            return _Verdict.WAIT  # states are not known yet; DOWN would be a guess
        if model.state is State.DOWN:
            raise UnavailableError(f"model {model.name} backend is down", _RETRY_AFTER_DOWN_S)
        if model.state is State.AWAKE:
            for other in self._competitors(model):
                if other.spec.priority > model.spec.priority:
                    return _Verdict.WAIT  # a more important model is waiting: yield at once
                if (
                    other.spec.priority == model.spec.priority
                    and now - model.awake_since >= self.config.min_awake_s
                ):
                    return _Verdict.WAIT  # we had our turn: let the waiting model swap in
            return _Verdict.GO
        if model.state in (State.WAKING, State.SLEEPING):
            return _Verdict.WAIT
        # ASLEEP: who is in the way?
        in_the_way = [
            other
            for other in self.models.values()
            if other is not model
            and other.spec.gpu_slots & model.spec.gpu_slots
            and other.state not in (State.ASLEEP, State.DOWN)
        ]
        if any(o.state in (State.WAKING, State.SLEEPING) for o in in_the_way):
            return _Verdict.WAIT
        if any(o.spec.priority > model.spec.priority for o in self._competitors(model)):
            return _Verdict.WAIT  # a more important model is also waiting: it goes first
        busy = [o for o in in_the_way if o.inflight]
        if busy:  # drain: never sleep a model that is serving requests ...
            self._preempt_if_due(model, busy, waited_s)  # ... unless it must give way
            return _Verdict.WAIT
        if any(
            o.spec.priority > model.spec.priority
            and now - o.last_used < self.config.priority_hold_s
            for o in in_the_way
        ):
            return _Verdict.WAIT  # never interrupt a more important model that just served
        return _Swap(model, in_the_way)

    def _preempt_if_due(
        self, model: ModelRuntime, busy: list[ModelRuntime], waited_s: float
    ) -> None:
        """Ask ``busy`` models to stop their running requests once ``model`` waited long enough.

        Only when every one of them has a strictly lower priority; the proxy does the stopping,
        and the swap happens as soon as the slots are given back. Called with the lock held.
        """
        limit = self.config.preempt_after_s
        if limit is None or waited_s < limit:
            return
        if any(o.spec.priority >= model.spec.priority for o in busy):
            return
        for victim in busy:
            if not victim.stop_requested:
                victim.stop_requested = True
                self._spawn(self._stop_requests(victim, model.name, waited_s))

    async def _stop_requests(self, victim: ModelRuntime, target: str, waited_s: float) -> None:
        """Tell the proxy to cancel the victim's running requests, after checking its counters.

        The victim is certainly busy now, so this is the moment to learn whether its token
        counters move; later they are what proves the engine stopped (see ``_drain``).
        """
        moving = await self._backend.activity_moves(victim.spec, _CALIBRATE_GAP_S)
        victim.counters_work = bool(moving) if moving is not None else None
        if not victim.stop_requested or victim.state is not State.AWAKE or not victim.inflight:
            return  # the requests ended (or the swap went ahead) while we were looking
        victim.preempt_event.set()
        detail = f"{victim.inflight} running request(s) stopped for {target}"
        counters = "counters move" if victim.counters_work else "no usable counters"
        self._event(victim, "preempt", f"{detail} (waited {waited_s:.0f}s, {counters})")
        log.warning("model %s: %s after %.0fs (%s)", victim.name, detail, waited_s, counters)

    def _competitors(self, model: ModelRuntime) -> list[ModelRuntime]:
        """Sleeping models that share a GPU with ``model`` and have requests waiting."""
        return [
            other
            for other in self.models.values()
            if other is not model
            and other.waiting
            and other.state is State.ASLEEP
            and other.spec.gpu_slots & model.spec.gpu_slots
        ]

    # --------------------------------------------------------------- public API
    async def acquire(self, name: str) -> ModelRuntime:
        """Wait until the model is awake and reserve a slot on it. Pair with ``release``."""
        model = self.resolve(name)
        started = time.monotonic()
        try:
            result = await self._acquire(model)
        except UnavailableError as exc:
            model.rejected += 1
            self._event(model, "rejected", str(exc))
            raise
        waited = time.monotonic() - started
        if waited > _MIN_REPORTED_WAIT_S:
            model.waits += 1
            model.wait_total_s += waited
            model.wait_max_s = max(model.wait_max_s, waited)
        return result

    async def _acquire(self, model: ModelRuntime) -> ModelRuntime:
        waiting_since = time.monotonic()
        model.waiting += 1
        try:
            while True:
                swap: _Swap | None = None
                async with self._cond:
                    verdict = self._decide(model, time.monotonic() - waiting_since)
                    if verdict is _Verdict.GO:
                        model.inflight += 1
                        model.last_used = time.monotonic()
                        model.preempt_event.clear()  # nobody more important is waiting any more
                        model.stop_requested = False
                        return model
                    if isinstance(verdict, _Swap):
                        swap = verdict
                        swap.target.state = State.WAKING
                        for other in swap.to_sleep:
                            other.state = State.SLEEPING
                    else:
                        # Read live, so a changed queue timeout also applies to waiting requests.
                        remaining = waiting_since + self.config.queue_timeout_s - time.monotonic()
                        if remaining <= 0:
                            raise UnavailableError(
                                f"timed out waiting for {model.name}", _RETRY_AFTER_QUEUE_S
                            )
                        # Re-evaluate at least every second: min_awake timers expire silently.
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(
                                self._cond.wait(), min(remaining, _RECHECK_INTERVAL_S)
                            )
                        continue
                # Run the swap outside the lock, shielded so a client disconnect cannot
                # leave a model stuck in WAKING/SLEEPING.
                task = self._spawn(self._run_swap(swap))
                try:
                    return await asyncio.shield(task)
                except asyncio.CancelledError:
                    # The swap still finishes and hands us a slot nobody wants: give it back.
                    task.add_done_callback(lambda t: self._release_if_ok(model, t))
                    raise
        finally:
            model.waiting -= 1

    def _release_if_ok(self, model: ModelRuntime, task: asyncio.Task[ModelRuntime]) -> None:
        if not task.cancelled() and task.exception() is None:
            self.release(model)

    def release(self, model: ModelRuntime, *, aborted: bool = False) -> None:
        """Give back a slot. Synchronous on purpose: must work while a request is cancelled.

        ``aborted`` means the request did not finish: the client left or it was stopped. vLLM
        only drops such a request a moment later, so the model must not be slept right away.
        """
        model.inflight = max(0, model.inflight - 1)
        model.last_used = time.monotonic()
        if aborted:
            model.aborted_at = model.last_used
        self._spawn(self._notify())

    @staticmethod
    def record_result(model: ModelRuntime, status: int | None) -> None:
        """Count a proxied request; ``status`` is None if the backend was unreachable."""
        model.requests += 1
        if status is None or status >= 400:
            model.errors += 1

    # ----------------------------------------------------------------- registry
    def _check_names(self, name: str, spec: ModelSpec, *, ignore: str | None = None) -> None:
        """Names must stay unambiguous: a request's model name must match exactly one model."""
        for other_name, other in self.models.items():
            if other_name == ignore:
                continue
            taken = {other_name, other.served_name}
            if name in taken or spec.served_name in taken:
                raise InvalidInputError(f"the name '{name}' or its served name is already in use")

    def _get(self, name: str) -> ModelRuntime:
        try:
            return self.models[name]
        except KeyError:
            raise NotFoundError(f"model '{name}' is not registered") from None

    @staticmethod
    def _require_idle(model: ModelRuntime, action: str) -> None:
        if model.state not in (State.ASLEEP, State.DOWN) or model.inflight or model.waiting:
            raise InvalidInputError(
                f"{model.name} is {model.state.value} with {model.inflight} running and "
                f"{model.waiting} waiting request(s): put it to sleep first to {action}"
            )

    async def register(self, name: str, spec: ModelSpec) -> ModelRuntime:
        """Start managing a container that is already running. It is put to sleep if awake."""
        async with self._cond:
            self._check_names(name, spec)
            model = ModelRuntime(name, spec)  # DOWN until probed: requests get a clean 503
            self.models[name] = model
        state = await self._probe(model)
        if state is State.AWAKE:
            async with self._cond:
                model.state = State.SLEEPING
            await self._go_to_sleep(model, "registered")
        else:
            await self._set_state(model, state)
        self._event(model, "registered", f"{state.value} on {spec.server} GPU {sorted(spec.gpus)}")
        return model

    async def update(self, name: str, spec: ModelSpec) -> ModelRuntime:
        """Change a model's settings. Where it runs can only change while it is idle."""
        async with self._cond:
            model = self._get(name)
            self._check_names(name, spec, ignore=name)
            old = model.spec
            moved = (old.url, old.served_name, old.server, old.gpus) != (
                spec.url,
                spec.served_name,
                spec.server,
                spec.gpus,
            )
            if moved:
                self._require_idle(model, "change its address, name, server or GPUs")
            model.spec = spec
            if moved:
                model.state = State.DOWN
            self._cond.notify_all()
        if moved:
            await self._set_state(model, await self._probe(model))
        self._event(model, "updated", f"priority {spec.priority}, idle {spec.idle_minutes:g} min")
        return model

    async def remove(self, name: str) -> None:
        """Stop managing a model (its container is left alone). It must be idle."""
        async with self._cond:
            model = self._get(name)
            self._require_idle(model, "remove it")
            del self.models[name]
            self._cond.notify_all()
        self._event(model, "removed")

    async def sleep_now(self, name: str) -> None:
        """Put an awake model to sleep right away (only if no request is running on it)."""
        async with self._cond:
            model = self._get(name)
            if model.state is State.ASLEEP:
                return
            if model.state is not State.AWAKE or model.inflight or model.waiting:
                raise InvalidInputError(
                    f"{name} is {model.state.value} with {model.inflight} running and "
                    f"{model.waiting} waiting request(s); try again when it is idle"
                )
            model.state = State.SLEEPING
        await self._go_to_sleep(model, "manual")

    async def reconfigure(self, config: EngineConfig) -> None:
        """Apply new timings at once; requests that are already waiting use them too."""
        async with self._cond:
            self.config = config
            self._backend.configure(
                sleep_level=config.sleep_level,
                sleep_timeout_s=config.sleep_timeout_s,
                wake_timeout_s=config.wake_timeout_s,
            )
            self._cond.notify_all()

    # ---------------------------------------------------------- background jobs
    async def startup(self) -> None:
        """Find out where every container really is, then put all awake ones to sleep.

        Meant to run in the background while the server already answers: requests for a
        model wait (up to the queue timeout) until this has finished.
        """
        self._starting = True
        try:
            for model in list(self.models.values()):
                model.state = await self._probe(model)
            for model in list(self.models.values()):
                if model.state is State.AWAKE:
                    async with self._cond:
                        model.state = State.SLEEPING
                    await self._go_to_sleep(model, "startup")
            summary = ", ".join(f"{n}={m.state.value}" for n, m in self.models.items())
            self._event(None, "startup", summary)
            for model in self.models.values():
                model.checked_at = time.monotonic()  # just probed: the next check is due later
        finally:
            async with self._cond:
                self._starting = False
                self._cond.notify_all()

    async def wait_until_started(self) -> None:
        """Return once ``startup`` has finished (at once if it never began)."""
        async with self._cond:
            await self._cond.wait_for(lambda: not self._starting)

    async def reap_once(self) -> None:
        """Sleep idle models, re-adopt containers that came back, notice ones that went away."""
        now = time.monotonic()
        idle: list[ModelRuntime] = []
        down: list[ModelRuntime] = []
        asleep: list[ModelRuntime] = []
        async with self._cond:
            for model in self.models.values():
                if (
                    model.state is State.AWAKE
                    and model.inflight == 0
                    and now - model.last_used > model.spec.idle_seconds
                ):
                    model.state = State.SLEEPING
                    idle.append(model)
                elif model.state is State.DOWN:
                    down.append(model)
                elif model.state is State.ASLEEP and now - model.checked_at >= _ASLEEP_CHECK_S:
                    model.checked_at = now
                    asleep.append(model)
        await asyncio.gather(*(self._go_to_sleep(m, "idle") for m in idle))
        for model in down:
            found = await self._probe(model)
            if found is State.DOWN:
                continue
            self._event(model, "back_online", found.value)
            if found is State.ASLEEP:
                await self._set_state(model, State.ASLEEP)
            else:
                async with self._cond:
                    model.state = State.SLEEPING
                await self._go_to_sleep(model, "adopted")
        await asyncio.gather(*(self._recheck_asleep(m) for m in asleep))

    async def _recheck_asleep(self, model: ModelRuntime) -> None:
        """A model we think is asleep may have been stopped, or restarted (fresh, so awake)."""
        found = await self._probe(model)
        if found is State.ASLEEP:
            return
        async with self._cond:
            if model.state is not State.ASLEEP:
                return  # a request started waking it while we asked: its state is newer
            if found is State.DOWN:
                model.state = State.DOWN
                self._cond.notify_all()
            else:
                model.state = State.SLEEPING
        if found is State.DOWN:
            self._event(model, "went_down", "container stopped or unreachable")
            log.warning("model %s is no longer reachable", model.name)
        else:
            self._event(model, "back_online", "awake")
            await self._go_to_sleep(model, "adopted")

    async def run_reaper(self) -> None:
        """Run ``reap_once`` forever."""
        while True:
            await asyncio.sleep(self.config.reaper_interval_s)
            try:
                await self.reap_once()
            except Exception:
                log.exception("reaper iteration failed")

    async def aclose(self) -> None:
        """Cancel outstanding background work."""
        for task in list(self._tasks):
            task.cancel()

    # ------------------------------------------------------------------- status
    def status(self) -> dict[str, ModelStatus]:
        """Live state and counters per model."""
        now = time.monotonic()
        out: dict[str, ModelStatus] = {}
        for name, m in self.models.items():
            idle = now - m.last_used
            counting_down = m.state is State.AWAKE and m.inflight == 0
            out[name] = ModelStatus(
                state=m.state.value,
                priority=m.spec.priority,
                gpus=sorted(m.spec.gpus),
                inflight=m.inflight,
                waiting=m.waiting,
                idle_s=round(idle, 1),
                sleeps_after_s=m.spec.idle_seconds,
                sleeps_in_s=round(max(0.0, m.spec.idle_seconds - idle), 1)
                if counting_down
                else None,
                requests=m.requests,
                errors=m.errors,
                rejected=m.rejected,
                wakes=m.wakes,
                sleeps=m.sleeps,
                last_wake_s=round(m.last_wake_s, 2) if m.last_wake_s is not None else None,
                avg_wake_s=round(m.wake_total_s / m.wakes, 2) if m.wakes else None,
                waits=m.waits,
                avg_wait_s=round(m.wait_total_s / m.waits, 2) if m.waits else None,
                max_wait_s=round(m.wait_max_s, 2) if m.waits else None,
            )
        return out

    def snapshot(self, event_limit: int = 60) -> StatusOut:
        """Everything the dashboard shows live, in one call."""
        gpus: dict[str, GpuHolder | None] = {}
        slots = sorted({s for m in self.models.values() for s in m.spec.gpu_slots})
        several_servers = len({server for server, _ in slots}) > 1
        for slot in slots:
            holder = next(
                (
                    m
                    for m in self.models.values()
                    if slot in m.spec.gpu_slots and m.state in HOLDS_GPU
                ),
                None,
            )
            server, number = slot
            key = f"{server} · GPU {number}" if several_servers else str(number)
            gpus[key] = GpuHolder(model=holder.name, state=holder.state.value) if holder else None
        return StatusOut(
            uptime_s=round(time.time() - self.started_at),
            models=self.status(),
            gpus=gpus,
            events=list(self.events)[-event_limit:][::-1],  # newest first
        )
