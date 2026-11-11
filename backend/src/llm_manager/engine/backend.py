"""HTTP client for one vLLM container's sleep-mode endpoints."""

import httpx

from llm_manager.core.models_config import ModelSpec

_PROBE_TIMEOUT_S = 5.0


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
