"""Login, logout and "who am I"."""

from fastapi import APIRouter, Request, Response, status

from llm_manager.api.deps import ContainerDep, CsrfSessionDep, SessionDep, client_ip
from llm_manager.core.settings import Settings
from llm_manager.schemas.auth import ChangePasswordRequest, LoginRequest, SessionInfo

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=int(settings.session_hours * 3600),
        httponly=True,  # not readable by page scripts
        secure=settings.cookie_secure,  # HTTPS only
        samesite="strict",  # never sent on cross-site requests
        path="/",
    )


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response, container: ContainerDep
) -> SessionInfo:
    """Exchange a username and password for a session cookie."""
    token, session = await container.login.login(
        body.username,
        body.password,
        client_ip(request, container),
        request.headers.get("user-agent"),
    )
    _set_session_cookie(response, token, container.settings)
    return SessionInfo(username=session.username, role=session.role, csrf_token=session.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(session: CsrfSessionDep, response: Response, container: ContainerDep) -> None:
    """End this session."""
    await container.sessions.end(session.session_id)
    response.delete_cookie(container.settings.session_cookie_name, path="/")


@router.get("/me")
async def me(session: SessionDep) -> SessionInfo:
    """The current user and the CSRF token to send with changes."""
    return SessionInfo(username=session.username, role=session.role, csrf_token=session.csrf_token)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    session: CsrfSessionDep,
    container: ContainerDep,
) -> None:
    """Change your own password. Your other sessions are logged out."""
    await container.users.change_own_password(
        session,
        body.current_password,
        body.new_password,
        ip=client_ip(request, container),
    )
