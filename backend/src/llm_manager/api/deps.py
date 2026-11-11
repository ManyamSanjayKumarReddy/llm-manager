"""FastAPI dependencies: who is calling, and are they allowed to?"""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from llm_manager.api.container import Container
from llm_manager.db.models import Role
from llm_manager.services.api_keys import ApiPrincipal
from llm_manager.services.sessions import SessionUser

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_BEARER_PREFIX = "bearer "
_MAX_IP_LENGTH = 64


def get_container(request: Request) -> Container:
    """The shared object graph."""
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def client_ip(request: Request, container: Container) -> str | None:
    """The caller's IP; with ``TRUST_PROXY`` it is the proxy's ``X-Real-IP`` header."""
    if container.settings.trust_proxy:
        forwarded = request.headers.get("x-real-ip")
        if forwarded:
            return forwarded[:_MAX_IP_LENGTH]
    return request.client.host if request.client else None


async def current_session(request: Request, container: ContainerDep) -> SessionUser:
    """The logged-in user, from the session cookie. 401 if there is none."""
    token = request.cookies.get(container.settings.session_cookie_name)
    session = await container.sessions.resolve(token)
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not logged in")
    return session


SessionDep = Annotated[SessionUser, Depends(current_session)]


async def csrf_protected(request: Request, session: SessionDep) -> SessionUser:
    """Like ``current_session``, and state-changing requests must carry the CSRF token."""
    if request.method not in _SAFE_METHODS:
        sent = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(sent.encode(), session.csrf_token.encode()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid CSRF token")
    return session


CsrfSessionDep = Annotated[SessionUser, Depends(csrf_protected)]


async def require_admin(session: CsrfSessionDep) -> SessionUser:
    """Admins only (and CSRF-protected when the request changes something)."""
    if session.role is not Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return session


AdminDep = Annotated[SessionUser, Depends(require_admin)]


async def api_principal(request: Request, container: ContainerDep) -> ApiPrincipal:
    """The API key holder calling ``/v1/*``. 401 if the key is missing, unknown or revoked."""
    header = request.headers.get("authorization", "")
    token = header[len(_BEARER_PREFIX) :] if header.lower().startswith(_BEARER_PREFIX) else None
    principal = await container.api_keys.authenticate(token)
    if principal is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")
    return principal


PrincipalDep = Annotated[ApiPrincipal, Depends(api_principal)]
