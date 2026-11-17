"""Talking to the Wakeful agent that runs on a GPU server."""

from typing import Any

import httpx

from llm_manager.core.errors import InvalidInputError, NotFoundError, UnavailableError
from llm_manager.db.models import Server

_READ_TIMEOUT_S = 15.0
_CHANGE_TIMEOUT_S = 75.0  # stopping vLLM can take 30 s; removing and restarting add to that
_RETRY_AFTER_S = 10
_SERVER_ERROR = 500


def _detail(response: httpx.Response) -> str:
    try:
        text = response.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return f"the agent answered {response.status_code}"
    return text if isinstance(text, str) else f"the agent answered {response.status_code}"


class AgentClient:
    """One server's agent: a base address and a bearer token."""

    def __init__(self, http: httpx.AsyncClient, server: Server) -> None:
        if not server.agent_url or not server.agent_token:
            raise InvalidInputError(
                f"{server.name} has no agent: add its address and token on the Servers page"
            )
        self._http = http
        self._server = server.name
        self._base = server.agent_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {server.agent_token}"}

    async def call(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        change: bool = False,
    ) -> Any:
        """Call the agent and return its JSON (``None`` for an empty answer)."""
        try:
            response = await self._http.request(
                method,
                f"{self._base}{path}",
                headers=self._headers,
                json=json,
                params=params,
                timeout=_CHANGE_TIMEOUT_S if change else _READ_TIMEOUT_S,
            )
        except httpx.HTTPError as error:
            raise UnavailableError(
                f"cannot reach the agent on {self._server} ({type(error).__name__}): "
                "is it running, and is the address right?",
                retry_after=_RETRY_AFTER_S,
            ) from error
        if response.is_success:
            return response.json() if response.content else None
        message = _detail(response)
        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise InvalidInputError(f"the agent on {self._server} refused the token")
        if response.status_code == httpx.codes.NOT_FOUND:
            raise NotFoundError(message)
        if response.status_code >= _SERVER_ERROR:
            raise UnavailableError(message, retry_after=_RETRY_AFTER_S)
        raise InvalidInputError(message)
