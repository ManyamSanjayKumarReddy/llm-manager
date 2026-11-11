"""User accounts: creation, changes and passwords."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from tortoise.exceptions import IntegrityError

from llm_manager.core import security
from llm_manager.core.errors import AuthenticationError, InvalidInputError, NotFoundError
from llm_manager.core.settings import Settings
from llm_manager.db.models import Role, User
from llm_manager.services.audit import AuditService
from llm_manager.services.sessions import SessionService, SessionUser


class UserService:
    """Manages accounts. Accounts are created by admins; there is no self-registration."""

    def __init__(self, settings: Settings, audit: AuditService, sessions: SessionService) -> None:
        self._settings = settings
        self._audit = audit
        self._sessions = sessions

    def _check_password(self, password: str, username: str) -> None:
        problem = security.password_problem(password, username, self._settings.min_password_length)
        if problem:
            raise InvalidInputError(problem)

    async def create(
        self,
        username: str,
        password: str,
        role: Role,
        *,
        actor: str,
        ip: str | None = None,
    ) -> User:
        """Create an account."""
        username = security.normalize_username(username)
        if not security.USERNAME_PATTERN.match(username):
            raise InvalidInputError(
                "username must be 3-64 characters: a-z, 0-9, dot, dash, underscore"
            )
        self._check_password(password, username)
        password_hash = await asyncio.to_thread(security.hash_password, password)
        try:
            user = await User.create(username=username, password_hash=password_hash, role=role)
        except IntegrityError:
            raise InvalidInputError("that username already exists") from None
        await self._audit.record(actor, "user.create", target=username, ip=ip, detail=role.value)
        return user

    async def page(
        self, *, q: str | None, role: Role | None, offset: int, limit: int
    ) -> tuple[list[User], int]:
        """One page of accounts by username, optionally filtered by name and role."""
        query = User.all()
        if q and q.strip():
            query = query.filter(username__icontains=q.strip().lower())
        if role is not None:
            query = query.filter(role=role)
        total = await query.count()
        return await query.order_by("username").offset(offset).limit(limit), total

    async def list_all(self) -> list[User]:
        """Every account, by username."""
        return await User.all().order_by("username")

    async def update(
        self,
        user_id: UUID,
        *,
        is_active: bool | None,
        role: Role | None,
        actor: str,
        ip: str | None,
    ) -> User:
        """Enable/disable an account or change its role. The last active admin is protected."""
        user = await User.get_or_none(id=user_id)
        if user is None:
            raise NotFoundError("user not found")
        new_active = user.is_active if is_active is None else is_active
        new_role = user.role if role is None else role
        loses_admin = (
            user.role is Role.ADMIN
            and user.is_active
            and (new_role is not Role.ADMIN or not new_active)
        )
        if loses_admin:
            others = await User.filter(role=Role.ADMIN, is_active=True).exclude(id=user_id).count()
            if others == 0:
                raise InvalidInputError("cannot remove or disable the last active admin")
        user.is_active, user.role = new_active, new_role
        await user.save(update_fields=["is_active", "role"])
        if not new_active:
            await self._sessions.end_all_for_user(user.id)
        await self._audit.record(
            actor,
            "user.update",
            target=user.username,
            ip=ip,
            detail=f"active={new_active} role={new_role.value}",
        )
        return user

    async def _set_password(self, user: User, new_password: str) -> None:
        self._check_password(new_password, user.username)
        user.password_hash = await asyncio.to_thread(security.hash_password, new_password)
        user.password_changed_at = datetime.now(UTC)
        user.failed_attempts = 0
        user.locked_until = None
        await user.save(
            update_fields=[
                "password_hash",
                "password_changed_at",
                "failed_attempts",
                "locked_until",
            ]
        )

    async def reset_password(
        self, user_id: UUID, new_password: str, *, actor: str, ip: str | None
    ) -> None:
        """An admin sets someone's password; that user is logged out everywhere."""
        user = await User.get_or_none(id=user_id)
        if user is None:
            raise NotFoundError("user not found")
        await self._set_password(user, new_password)
        await self._sessions.end_all_for_user(user.id)
        await self._audit.record(actor, "password.reset", target=user.username, ip=ip)

    async def change_own_password(
        self, me: SessionUser, current: str, new: str, *, ip: str | None
    ) -> None:
        """Change your own password; your other sessions are ended."""
        user = await User.get(id=me.user_id)
        correct = await asyncio.to_thread(security.verify_password, user.password_hash, current)
        if not correct:
            await self._audit.record(me.username, "password.change_denied", ip=ip)
            raise AuthenticationError
        await self._set_password(user, new)
        await self._sessions.end_all_for_user(user.id, keep=me.session_id)
        await self._audit.record(me.username, "password.change", ip=ip)

    async def unlock(self, username: str, *, actor: str) -> bool:
        """Clear a lockout. Returns False if the user does not exist."""
        updated = await User.filter(username=security.normalize_username(username)).update(
            failed_attempts=0, locked_until=None
        )
        await self._audit.record(actor, "user.unlock", target=username)
        return bool(updated)
