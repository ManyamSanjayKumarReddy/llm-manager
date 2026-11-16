"""HTTP client for one vLLM container's sleep-mode endpoints."""

import asyncio
import re
import time

import httpx

from llm_manager.core.models_config import ModelSpec

_PROBE_TIMEOUT_S = 5.0
_IDLE_POLL_S = 0.25
_IDLE_GRACE_S = 0.3  # after the engine reports idle, let the last GPU step finish
_IDLE_LIMIT_S = 20.0
_RUNNING_GAUGE = re.compile(
    r"^vllm:num_requests_(?:running|waiting)(?:\{[^}]*\})?\s+([0-9.eE+-]+)\s*$", re.MULTILINE
)


class BackendError(Exception):
    """A vLLM container could not be reached or gave an unusable answer."""


class VllmBackend:
    """Calls ``/sleep``, ``/wake_up`` and ``/is_sleeping`` (needs VLLM_SERVER_DEV_MODE=1)."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        sleep_level: int,
        sleep_timeout_s: float,
        wake_timeout_s: float,
    ) -> None:
        self._client = client
        self._sleep_level = sleep_level
        self._sleep_timeout_s = sleep_timeout_s
        self._wake_timeout_s = wake_timeout_s

    def configure(self, *, sleep_level: int, sleep_timeout_s: float, wake_timeout_s: float) -> None:
        """Change the sleep level and timeouts used from the next call on."""
        self._sleep_level = sleep_level
        self._sleep_timeout_s = sleep_timeout_s
        self._wake_timeout_s = wake_timeout_s

    @staticmethod
    def _headers(spec: ModelSpec) -> dict[str, str]:
        key = spec.backend_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def _call(
        self,
        method: str,
        spec: ModelSpec,
        path: str,
        *,
        timeout_s: float,
        params: dict[str, int] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                f"{spec.url.rstrip('/')}{path}",
                params=params,
                headers=self._headers(spec),
                timeout=timeout_s,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BackendError(str(exc) or type(exc).__name__) from exc
        return response

    async def _engine_load(self, spec: ModelSpec) -> float | None:
        """Requests vLLM is still running or has queued, or None if it does not say."""
        try:
            response = await self._call("GET", spec, "/metrics", timeout_s=_PROBE_TIMEOUT_S)
        except BackendError:
            return None
        gauges = _RUNNING_GAUGE.findall(response.text)
        return sum(float(g) for g in gauges) if gauges else None

    async def _wait_until_engine_idle(self, spec: ModelSpec) -> None:
        """Do not free GPU memory under a running step.

        When a request is cancelled (client left, or stopped for a more important model) vLLM
        keeps working on it until its next scheduling step. Sleeping in that moment unmaps
        memory the kernel is using and kills the engine ("illegal memory access"), so wait
        until vLLM itself reports nothing running.
        """
        deadline = time.monotonic() + _IDLE_LIMIT_S
        waited = False
        while (load := await self._engine_load(spec)) is not None and load > 0:
            if time.monotonic() >= deadline:
                raise BackendError(f"engine still busy after {_IDLE_LIMIT_S:.0f}s, not sleeping it")
            waited = True
            await asyncio.sleep(_IDLE_POLL_S)
        if waited:
            await asyncio.sleep(_IDLE_GRACE_S)

    async def sleep(self, spec: ModelSpec) -> None:
        """Move the model's weights to CPU RAM and free its GPU memory."""
        await self._wait_until_engine_idle(spec)
        await self._call(
            "POST",
            spec,
            "/sleep",
            timeout_s=self._sleep_timeout_s,
            params={"level": self._sleep_level},
        )

    async def wake(self, spec: ModelSpec) -> None:
        """Copy the model's weights back to the GPU."""
        await self._call("POST", spec, "/wake_up", timeout_s=self._wake_timeout_s)

    async def is_sleeping(self, spec: ModelSpec) -> bool:
        """Ask the container whether it is asleep."""
        response = await self._call("GET", spec, "/is_sleeping", timeout_s=_PROBE_TIMEOUT_S)
        try:
            return bool(response.json()["is_sleeping"])
        except (ValueError, KeyError, TypeError) as exc:
            raise BackendError("unexpected reply from /is_sleeping") from exc
