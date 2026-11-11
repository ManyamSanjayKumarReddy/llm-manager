"""The OpenAI-compatible endpoint that programs call with an API key."""

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from llm_manager.api.deps import ContainerDep, PrincipalDep
from llm_manager.services.recorder import RequestRecord

router = APIRouter(prefix="/v1", tags=["openai-compatible"])

_BAD_GATEWAY = 502


@router.get("/models")
async def list_models(principal: PrincipalDep, container: ContainerDep) -> dict[str, Any]:
    """The models this key may use. Does not wake anything."""
    return {
        "object": "list",
        "data": [
            {"id": name, "object": "model", "owned_by": "llm-manager"}
            for name in container.manager.models
            if principal.may_use(name)
        ],
    }


async def _read_body(request: Request) -> tuple[dict[str, Any], str]:
    try:
        body = await request.json()
        name = body["model"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "body must be JSON with a 'model'"
        ) from None
    if not isinstance(body, dict) or not isinstance(name, str):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "body must be JSON with a 'model'")
    return body, name


@router.post("/{path:path}")
async def proxy(
    path: str, request: Request, principal: PrincipalDep, container: ContainerDep
) -> StreamingResponse:
    """Forward a request to the model, waking it first if it is asleep."""
    container.api_keys.enforce_rate_limit(principal)
    body, name = await _read_body(request)
    manager = container.manager
    model = manager.resolve(name)  # 404 for unknown models
    if not principal.may_use(model.name):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this API key may not use that model")

    started = time.monotonic()
    await manager.acquire(model.name)  # waits for the model to be awake; 503 on timeout
    queue_wait_ms = int((time.monotonic() - started) * 1000)

    released = False

    def finish(status_code: int | None) -> None:
        """Release the model slot and log the request, exactly once."""
        nonlocal released
        if released:
            return
        released = True
        manager.release(model)
        container.recorder.record_request(
            RequestRecord(
                model=model.name,
                api_key_id=principal.id,
                status=status_code or _BAD_GATEWAY,
                duration_ms=int((time.monotonic() - started) * 1000),
                queue_wait_ms=queue_wait_ms,
            )
        )

    try:
        body["model"] = model.served_name
        headers = {"Content-Type": "application/json"}
        if model.spec.backend_key:
            headers["Authorization"] = f"Bearer {model.spec.backend_key}"
        upstream_request = container.http.build_request(
            "POST", f"{model.spec.url.rstrip('/')}/v1/{path}", json=body, headers=headers
        )
        upstream = await container.http.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        finish(None)
        manager.record_result(model, None)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"backend error: {exc}") from exc
    manager.record_result(model, upstream.status_code)

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            finish(upstream.status_code)  # the slot is held until the last byte is sent

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
