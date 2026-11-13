"""The OpenAI-compatible endpoint that programs call with an API key."""

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from llm_manager.api.deps import ContainerDep, PrincipalDep
from llm_manager.core.errors import UnavailableError
from llm_manager.core.usage import JsonTail, SseUsage, TokenUsage, wants_stream_usage
from llm_manager.services.recorder import RequestRecord

router = APIRouter(prefix="/v1", tags=["openai-compatible"])

_BAD_GATEWAY = 502
_STOPPED = 503
_RETRY_AFTER_STOPPED_S = 15
_STOPPED_MESSAGE = "stopped so a higher-priority model could use the GPU; retry shortly"
_STOPPED_EVENT = (
    b'data: {"error": {"message": "' + _STOPPED_MESSAGE.encode() + b'", "type": '
    b'"llm_manager_error", "code": "model_unavailable"}}\n\ndata: [DONE]\n\n'
)


class _StoppedError(Exception):
    """The model was asked to give up its running requests for a more important one."""


class _Interruptible:
    """Awaits upstream work, but gives up as soon as the model is asked to stop."""

    def __init__(self, event: asyncio.Event) -> None:
        self._stop = asyncio.ensure_future(event.wait())

    async def run[T](self, awaitable: Awaitable[T]) -> T:
        """Return the work's result, or raise ``_StoppedError`` (and cancel the work) on a stop."""
        work = asyncio.ensure_future(awaitable)
        try:
            await asyncio.wait({work, self._stop}, return_when=asyncio.FIRST_COMPLETED)
            if not work.done():
                raise _StoppedError
            return work.result()
        finally:
            if not work.done():
                work.cancel()  # closes the upstream connection, so vLLM drops the request

    def close(self) -> None:
        """Stop watching; call once the request is over."""
        self._stop.cancel()


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
    stream_usage = wants_stream_usage(path, body)  # ask vLLM to report tokens for streams too
    manager = container.manager
    model = manager.resolve(name)  # 404 for unknown models
    if not principal.may_use(model.name):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "this API key may not use that model")

    started = time.monotonic()
    await manager.acquire(model.name)  # waits for the model to be awake; 503 on timeout
    queue_wait_ms = int((time.monotonic() - started) * 1000)

    released = False

    def finish(status_code: int | None, usage: TokenUsage | None = None) -> None:
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
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
            )
        )

    stop = _Interruptible(model.preempt_event)
    try:
        body["model"] = model.served_name
        headers = {"Content-Type": "application/json"}
        if model.spec.backend_key:
            headers["Authorization"] = f"Bearer {model.spec.backend_key}"
        upstream_request = container.http.build_request(
            "POST", f"{model.spec.url.rstrip('/')}/v1/{path}", json=body, headers=headers
        )
        upstream = await stop.run(container.http.send(upstream_request, stream=True))
    except _StoppedError:
        stop.close()
        finish(_STOPPED)
        manager.record_result(model, _STOPPED)
        raise UnavailableError(_STOPPED_MESSAGE, _RETRY_AFTER_STOPPED_S) from None
    except httpx.HTTPError as exc:
        stop.close()
        finish(None)
        manager.record_result(model, None)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"backend error: {exc}") from exc
    except BaseException:
        stop.close()
        finish(None)  # never leave the slot taken, e.g. when the server is shutting down
        raise
    manager.record_result(model, upstream.status_code)
    is_event_stream = upstream.headers.get("content-type", "").startswith("text/event-stream")

    # Tokens are read from what passes through (usage is reported at the very end of a reply).
    events = SseUsage(strip=stream_usage is False) if is_event_stream else None
    tail = JsonTail()

    async def stream() -> AsyncIterator[bytes]:
        final = upstream.status_code
        chunks = upstream.aiter_raw().__aiter__()
        try:
            while True:
                try:
                    chunk = await stop.run(anext(chunks))
                except StopAsyncIteration:
                    break
                except _StoppedError:
                    final = _STOPPED
                    if is_event_stream:
                        yield _STOPPED_EVENT
                    break
                if events is None:
                    tail.feed(chunk)
                    yield chunk
                elif out := events.feed(chunk):
                    yield out
            if events is not None and final != _STOPPED and (rest := events.finish()):
                yield rest
        finally:
            stop.close()
            await upstream.aclose()
            usage = events.usage if events is not None else tail.usage()
            finish(final, usage)  # the slot is held until the last byte is sent

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )
