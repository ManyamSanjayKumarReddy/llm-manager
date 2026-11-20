"""Talking to the Wakeful agent that runs on a GPU server."""

from typing import Any

import httpx

from llm_manager.core.errors import InvalidInputError, NotFoundError, UnavailableError
from llm_manager.core.routing import for_server
from llm_manager.db.models import Server

_READ_TIMEOUT_S = 15.0
_CHANGE_TIMEOUT_S = 75.0  # stopping vLLM can take 30 s; removing and restarting add to that
_CREATE_TIMEOUT_S = 1860.0  # creating may first download a multi-gigabyte image (agent: 30 min)
_RETRY_AFTER_S = 10
_SERVER_ERROR = 500


def _timeout(*, change: bool, long: bool) -> float:
    return _CREATE_TIMEOUT_S if long else _CHANGE_TIMEOUT_S if change else _READ_TIMEOUT_S


def _detail(response: httpx.Response) -> str:
    try:
        text = response.json()["detail"]
    except (ValueError, KeyError, TypeError):
        return f"the agent answered {response.status_code}"
    return text if isinstance(text, str) else f"the agent answered {response.status_code}"


_TUNNEL_BASE = "http://agent.tunnel.invalid"  # never looked up: the transport answers it


class AgentClient:
    """One server's agent: reached by address and token, or through the connection it opened."""

    def __init__(self, http: httpx.AsyncClient, server: Server) -> None:
        self._http = http
        self._server = server.name
        self._extensions: dict[str, object] = {}
        if server.tunnel_token_hash:
            # The agent dialled in; the shared client's transport finds its connection by name.
            self._base = _TUNNEL_BASE
            self._headers: dict[str, str] = {}
            self._extensions = for_server(server.name, "agent")
        elif server.agent_url and server.agent_token:
            self._base = server.agent_url.rstrip("/")
            self._headers = {"Authorization": f"Bearer {server.agent_token}"}
        else:
            raise InvalidInputError(
                f"{server.name} has no agent: add its address and token on the Servers page, "
                "or connect one"
            )

    async def call(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        change: bool = False,
        long: bool = False,
    ) -> Any:
        """Call the agent and return its JSON (``None`` for an empty answer)."""
        try:
            response = await self._http.request(
                method,
                f"{self._base}{path}",
                headers=self._headers,
                json=json,
                params=params,
                timeout=_timeout(change=change, long=long),
                extensions=self._extensions,
            )
        except httpx.HTTPError as error:
            raise UnavailableError(
                f"cannot reach the agent on {self._server} ({type(error).__name__}): "
                "is it running, and is the address right?"
                if not self._extensions
                else f"the agent on {self._server} is not connected: is it running there?",
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
