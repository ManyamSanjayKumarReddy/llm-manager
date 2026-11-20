"""Which server an outgoing call is for, so a server that connects out can be reached.

Calls to vLLM and to the agents all go through one HTTP client. A call carries the name of the
server it is for as a request extension; the client's transport (``services.tunnel``) then sends it
down that server's connection if the server connects out, and by its address otherwise.
"""

from typing import Any, Literal

SERVER_KEY = "wakeful.server"
TARGET_KEY = "wakeful.target"


def for_server(server: str, target: Literal["vllm", "agent"] = "vllm") -> dict[str, Any]:
    """The ``extensions`` to pass to an httpx call that is meant for ``server``."""
    return {SERVER_KEY: server, TARGET_KEY: target}
