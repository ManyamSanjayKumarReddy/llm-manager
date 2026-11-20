"""The command a client runs on a GPU server to install the agent: ``/install-agent.sh``.

The script is public on purpose (``curl`` fetches it before any login) and holds no secret: the
connection token is given to it on the command line. It is a template; the address of this Wakeful
and the name of the agent's Docker image are filled in when it is served.
"""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from llm_manager.api.deps import ContainerDep

router = APIRouter(tags=["install"])

_SCRIPT = Path(__file__).resolve().parents[2] / "assets" / "install-agent.sh"
# Both end up inside a shell script, so only plain characters are allowed.
_HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9][A-Za-z0-9._-]{0,127})?$")
_TAGGED_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_LOCAL = {"localhost", "127.0.0.1"}


def _origin(request: Request) -> tuple[str, str]:
    """This Wakeful's public address (https unless it is local) and the same as a websocket."""
    host = request.headers.get("host", "")
    if not _HOST.fullmatch(host):
        raise HTTPException(400, "unusable Host header")
    local = host.split(":")[0] in _LOCAL
    secure = not local or request.url.scheme == "https"
    return f"{'https' if secure else 'http'}://{host}", f"{'wss' if secure else 'ws'}://{host}"


def render(template: str, request: Request, image: str, vllm_image: str) -> str:
    """Fill the address and image into the script."""
    if not _IMAGE.fullmatch(image):
        raise HTTPException(500, "the agent image name in the settings is not valid")
    if not _TAGGED_IMAGE.fullmatch(vllm_image):
        raise HTTPException(500, "VLLM_IMAGE in the settings must look like repository:tag")
    origin, websocket = _origin(request)
    return (
        template.replace("__WAKEFUL_URL__", origin)
        .replace("__CONNECT_URL__", f"{websocket}/api/agent/connect")
        .replace("__AGENT_IMAGE__", image)
        .replace("__VLLM_IMAGE__", vllm_image)
    )


@router.get("/install-agent.sh", response_class=PlainTextResponse)
async def install_script(request: Request, container: ContainerDep) -> PlainTextResponse:
    """The installer, ready to pipe into ``sudo bash``."""
    settings = container.settings
    body = render(
        _SCRIPT.read_text(encoding="utf-8"),
        request,
        settings.agent_docker_image,
        settings.vllm_image,
    )
    return PlainTextResponse(
        body, media_type="text/x-shellscript", headers={"Cache-Control": "no-store"}
    )
