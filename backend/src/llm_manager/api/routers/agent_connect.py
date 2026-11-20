"""The endpoint GPU-server agents dial into (the enrollment token is the key, no login)."""

import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, status

from llm_manager.api.container import Container
from llm_manager.db.models import Server

router = APIRouter(tags=["agent"])
log = logging.getLogger(__name__)
_BEARER = "bearer "


def _token(header: str | None) -> str:
    if header is not None and header.lower().startswith(_BEARER):
        return header[len(_BEARER) :].strip()
    return ""


@router.websocket("/api/agent/connect")
async def connect(ws: WebSocket) -> None:
    """Hold an agent's connection open; Wakeful sends its calls for that server down it."""
    container: Container = ws.app.state.container
    token = _token(ws.headers.get("authorization"))
    server = await container.servers.authenticate(token) if token else None
    if server is None:
        # Closing before accepting makes the handshake fail with HTTP 403.
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await Server.filter(id=server.id).update(tunnel_last_seen=datetime.now(UTC))
    try:
        await container.hub.serve(server.name, ws)
    finally:
        await asyncio.shield(Server.filter(id=server.id).update(tunnel_last_seen=datetime.now(UTC)))
