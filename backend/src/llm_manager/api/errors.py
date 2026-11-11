"""Maps domain errors to HTTP responses."""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from llm_manager.core.errors import (
    AuthenticationError,
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    UnavailableError,
    UnknownModelError,
)

_OPENAI_PREFIX = "/v1/"
_HTTP_CODES = {401: "unauthorized", 403: "forbidden", 404: "not_found"}
_GENERIC_AUTH_MESSAGE = "Invalid credentials, or too many attempts. Try again later."


def _body(request: Request, message: str, code: str) -> dict[str, object]:
    """``/v1/*`` answers in OpenAI's error format so standard clients understand it."""
    if request.url.path.startswith(_OPENAI_PREFIX):
        return {"error": {"message": message, "type": "llm_manager_error", "code": code}}
    return {"detail": message}


def _respond(
    request: Request, status_code: int, message: str, code: str, retry_after: int | None = None
) -> JSONResponse:
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return JSONResponse(_body(request, message, code), status_code=status_code, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers for every expected failure."""

    @app.exception_handler(AuthenticationError)
    async def _auth(request: Request, _: AuthenticationError) -> JSONResponse:
        return _respond(
            request, status.HTTP_401_UNAUTHORIZED, _GENERIC_AUTH_MESSAGE, "unauthorized"
        )

    @app.exception_handler(RateLimitedError)
    async def _rate(request: Request, exc: RateLimitedError) -> JSONResponse:
        return _respond(
            request,
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests.",
            "rate_limited",
            exc.retry_after,
        )

    @app.exception_handler(InvalidInputError)
    async def _invalid(request: Request, exc: InvalidInputError) -> JSONResponse:
        return _respond(request, status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc), "invalid_input")

    @app.exception_handler(NotFoundError)
    async def _missing(request: Request, exc: NotFoundError) -> JSONResponse:
        return _respond(request, status.HTTP_404_NOT_FOUND, str(exc), "not_found")

    @app.exception_handler(UnknownModelError)
    async def _unknown_model(request: Request, exc: UnknownModelError) -> JSONResponse:
        return _respond(
            request, status.HTTP_404_NOT_FOUND, f"unknown model '{exc}'", "model_not_found"
        )

    @app.exception_handler(UnavailableError)
    async def _unavailable(request: Request, exc: UnavailableError) -> JSONResponse:
        return _respond(
            request,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            str(exc),
            "model_unavailable",
            exc.retry_after,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        return _respond(request, exc.status_code, str(exc.detail), code)
