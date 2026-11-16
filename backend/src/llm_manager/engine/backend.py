"""HTTP client for one vLLM container's sleep-mode endpoints."""

import asyncio
import re
import time

import httpx

from llm_manager.core.models_config import ModelSpec

_PROBE_TIMEOUT_S = 5.0
_POLL_S = 0.5  # how often the token counters are read while waiting for a quiet engine
# Counters that only move while the engine works on tokens (unlike the "running" gauge, which
# keeps its last value when the engine stops, and stays 0 when vLLM runs with stats off).
_TOKEN_COUNTERS = re.compile(
    r"^vllm:(?:prompt|generation)_tokens_total(?:\{[^}]*\})?\s+([0-9.eE+-]+)\s*$", re.MULTILINE
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

    async def activity(self, spec: ModelSpec) -> float | None:
        """Tokens the engine has processed so far, or None if vLLM does not report them."""
        try:
            response = await self._call("GET", spec, "/metrics", timeout_s=_PROBE_TIMEOUT_S)
        except BackendError:
            return None
        values = _TOKEN_COUNTERS.findall(response.text)
        return sum(float(v) for v in values) if values else None

    async def activity_moves(self, spec: ModelSpec, gap_s: float) -> bool | None:
        """Do the token counters move? Only meaningful while the engine is busy.

        None if they cannot be read. False while busy means vLLM keeps no stats
        (``--disable-log-stats``), so the counters cannot say when the engine is idle.
        """
        first = await self.activity(spec)
        if first is None:
            return None
        await asyncio.sleep(gap_s)
        second = await self.activity(spec)
        return None if second is None else second != first

    async def wait_until_quiet(self, spec: ModelSpec, *, quiet_s: float, limit_s: float) -> float:
        """Wait until the engine has processed no tokens for ``quiet_s``; return the time waited.

        Raises BackendError if it is still working after ``limit_s`` (or stops answering).
        """
        started = time.monotonic()
        last = await self.activity(spec)
        quiet_since = started
        while True:
            if last is None:
                raise BackendError("engine activity could not be read")
            await asyncio.sleep(_POLL_S)
            now = time.monotonic()
            current = await self.activity(spec)
            if current != last:
                last, quiet_since = current, now
            elif now - quiet_since >= quiet_s:
                return now - started
            if now - started >= limit_s:
                raise BackendError(f"engine still working {limit_s:.0f}s after the stop")

    async def sleep(self, spec: ModelSpec) -> None:
        """Move the model's weights to CPU RAM and free its GPU memory."""
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
