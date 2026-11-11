"""Login: password check, lockout and per-IP rate limiting."""

import asyncio
from datetime import UTC, datetime, timedelta

from tortoise.expressions import F

from llm_manager.core import security
from llm_manager.core.errors import AuthenticationError, RateLimitedError
from llm_manager.core.settings import Settings
from llm_manager.db.models import User
from llm_manager.services.audit import AuditService
from llm_manager.services.sessions import SessionService, SessionUser

_MAX_USERNAME_LENGTH = 64


class LoginService:
    """Authenticates users. Every failure looks the same to the caller."""

    def __init__(self, settings: Settings, sessions: SessionService, audit: AuditService) -> None:
        self._settings = settings
        self._sessions = sessions
        self._audit = audit
        self._ip_limiter = security.SlidingWindowLimiter(settings.login_ip_limit_per_min, 60)

    async def login(
        self, username: str, password: str, ip: str | None, user_agent: str | None
    ) -> tuple[str, SessionUser]:
        """Return ``(session_token, session_user)`` or raise.

        Raises:
            RateLimitedError: too many attempts from this IP address.
            AuthenticationError: wrong credentials, locked or disabled account.
        """
        allowed, retry_after = self._ip_limiter.check(ip or "unknown")
        if not allowed:
            raise RateLimitedError(retry_after)

        username = security.normalize_username(username)[:_MAX_USERNAME_LENGTH]
        user = await User.get_or_none(username=username)
        if user is None:
            # Same work as a real check, so timing does not reveal which usernames exist.
            await asyncio.to_thread(security.verify_password, security.DUMMY_HASH, password)
            await self._audit.record(username or "?", "login.fail", ip=ip, detail="unknown user")
            raise AuthenticationError

        now = datetime.now(UTC)
        locked = user.locked_until is not None and user.locked_until > now
        correct = await asyncio.to_thread(security.verify_password, user.password_hash, password)
        if locked or not user.is_active:
            reason = "locked" if locked else "disabled"
            await self._audit.record(username, "login.blocked", ip=ip, detail=reason)
            raise AuthenticationError
        if not correct:
            await self._register_failure(user, ip)
            raise AuthenticationError

        if security.needs_rehash(user.password_hash):
            user.password_hash = await asyncio.to_thread(security.hash_password, password)
        user.failed_attempts, user.locked_until, user.last_login_at = 0, None, now
        await user.save(
            update_fields=["password_hash", "failed_attempts", "locked_until", "last_login_at"]
        )
        result = await self._sessions.create(user, ip, user_agent)
        await self._audit.record(username, "login.ok", ip=ip)
        return result

    async def _register_failure(self, user: User, ip: str | None) -> None:
        """Count a wrong password atomically; lock the account after too many."""
        await User.filter(id=user.id).update(failed_attempts=F("failed_attempts") + 1)
        fresh = await User.get(id=user.id)
        if fresh.failed_attempts >= self._settings.lockout_attempts:
            until = datetime.now(UTC) + timedelta(minutes=self._settings.lockout_minutes)
            await User.filter(id=user.id).update(failed_attempts=0, locked_until=until)
            await self._audit.record(
                user.username, "login.lockout", ip=ip, detail=f"until {until.isoformat()}"
            )
        else:
            await self._audit.record(user.username, "login.fail", ip=ip, detail="wrong password")
