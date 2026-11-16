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
_VERSION = re.compile(r"(\d+)\.(\d+)")
_SLEEP_ABORTS_FROM = (0, 17)  # first vLLM release whose /sleep aborts in-flight requests
_PATCH_MARKER = "abortsleep"  # added to the version by scripts/vllm-abort-sleep


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

    async def sleep_aborts_requests(self, spec: ModelSpec) -> bool:
        """Does this vLLM abort running requests itself when it is put to sleep?

        From 0.17 on, ``/sleep`` pauses the scheduler and aborts every in-flight request before it
        frees GPU memory. Older versions free the memory under them, which kills the engine,
        unless the image carries ``scripts/vllm-abort-sleep`` (its version ends in "+abortsleep").
        """
        try:
            response = await self._call("GET", spec, "/version", timeout_s=_PROBE_TIMEOUT_S)
            version = str(response.json()["version"])
        except (BackendError, ValueError, KeyError, TypeError):
            return False
        if _PATCH_MARKER in version:
            return True
        found = _VERSION.match(version)
        return found is not None and (int(found[1]), int(found[2])) >= _SLEEP_ABORTS_FROM

    async def _counters(self, spec: ModelSpec) -> tuple[float | None, str]:
        """The engine's token total, or None plus the reason it could not be read."""
        try:
            response = await self._call("GET", spec, "/metrics", timeout_s=_PROBE_TIMEOUT_S)
        except BackendError as exc:
            return None, f"/metrics unreachable ({exc})"
        values = _TOKEN_COUNTERS.findall(response.text)
        if not values:
            return None, "/metrics has no token counters"
        return sum(float(v) for v in values), ""

    async def activity(self, spec: ModelSpec) -> float | None:
        """Tokens the engine has processed so far, or None if vLLM does not report them."""
        return (await self._counters(spec))[0]

    async def check_counters(self, spec: ModelSpec, gap_s: float) -> str:
        """Can the token counters prove the engine idle? Call it while the engine is busy.

        Returns "" if they move (they can), else the reason they cannot: unreachable, missing,
        or frozen (vLLM keeps no stats, so they stand still even while it works).
        """
        first, problem = await self._counters(spec)
        if first is None:
            return problem
        await asyncio.sleep(gap_s)
        second, problem = await self._counters(spec)
        if second is None:
            return problem
        return "" if second != first else "token counters stand still while the engine is busy"

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
