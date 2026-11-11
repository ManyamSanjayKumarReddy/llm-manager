"""Browser login sessions."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from llm_manager.core import security
from llm_manager.core.settings import Settings
from llm_manager.db.models import Role, Session, User

_TOUCH_AFTER = timedelta(seconds=60)  # update last_seen at most this often
_MAX_USER_AGENT_LENGTH = 300


@dataclass(frozen=True)
class SessionUser:
    """The logged-in user behind a valid session."""

    session_id: UUID
    user_id: UUID
    username: str
    role: Role
    csrf_token: str


class SessionService:
    """Creates, validates and ends sessions. Only token digests are stored."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def create(
        self, user: User, ip: str | None, user_agent: str | None
    ) -> tuple[str, SessionUser]:
        """Start a session. Returns the secret token (for the cookie) and the session user."""
        token = security.new_token()
        session = await Session.create(
            user=user,
            token_hash=security.digest(token),
            csrf_token=security.new_token(),
            expires_at=datetime.now(UTC) + timedelta(hours=self._settings.session_hours),
            ip=ip,
            user_agent=(user_agent or "")[:_MAX_USER_AGENT_LENGTH],
        )
        return token, SessionUser(session.id, user.id, user.username, user.role, session.csrf_token)

    async def resolve(self, token: str | None) -> SessionUser | None:
        """Return the user for a session token, or None if it is unknown, expired or idle."""
        if not token:
            return None
        session = await Session.get_or_none(token_hash=security.digest(token)).select_related(
            "user"
        )
        if session is None:
            return None
        now = datetime.now(UTC)
        idle_until = session.last_seen_at + timedelta(minutes=self._settings.session_idle_minutes)
        if session.expires_at <= now or idle_until <= now or not session.user.is_active:
            await self.end(session.id)
            return None
        if now - session.last_seen_at > _TOUCH_AFTER:
            await Session.filter(id=session.id).update(last_seen_at=now)
        user = session.user
        return SessionUser(session.id, user.id, user.username, user.role, session.csrf_token)

    async def end(self, session_id: UUID) -> None:
        """Log one session out."""
        await Session.filter(id=session_id).delete()

    async def end_all_for_user(self, user_id: UUID, *, keep: UUID | None = None) -> None:
        """Log a user out everywhere, optionally keeping one session."""
        query = Session.filter(user_id=user_id)
        if keep is not None:
            query = query.exclude(id=keep)
        await query.delete()
