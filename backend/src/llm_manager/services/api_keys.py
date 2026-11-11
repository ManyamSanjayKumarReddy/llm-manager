"""API keys for programs calling ``/v1/*``."""

from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Literal
from uuid import UUID

from llm_manager.core import security
from llm_manager.core.errors import InvalidInputError, NotFoundError, RateLimitedError
from llm_manager.db.models import ApiKey, User
from llm_manager.services.audit import AuditService

KeyStatus = Literal["active", "revoked"]
KEY_PREFIX = "lm_"
_PREFIX_SHOWN = 10  # characters of the token kept for recognition
_MAX_TOKEN_LENGTH = 200
_TOUCH_INTERVAL_S = 60.0  # update last_used_at at most this often per key


@dataclass(frozen=True)
class ApiPrincipal:
    """The caller behind a valid API key."""

    id: UUID
    label: str
    allowed_models: list[str] | None
    rpm_limit: int | None

    def may_use(self, model_name: str) -> bool:
        """True if this key may call the model."""
        return self.allowed_models is None or model_name in self.allowed_models


class ApiKeyService:
    """Creates, verifies and revokes API keys. Only SHA-256 digests are stored."""

    def __init__(self, audit: AuditService) -> None:
        self._audit = audit
        self._limiters: dict[UUID, security.SlidingWindowLimiter] = {}
        self._last_touched: dict[UUID, float] = {}

    async def create(
        self,
        label: str,
        *,
        created_by: User | None,
        allowed_models: list[str] | None,
        rpm_limit: int | None,
        actor: str,
        ip: str | None = None,
    ) -> tuple[ApiKey, str]:
        """Create a key. The plain token is returned once and never stored."""
        label = label.strip()
        if not label:
            raise InvalidInputError("label must not be empty")
        token = security.new_token(KEY_PREFIX)
        key = await ApiKey.create(
            label=label,
            prefix=token[:_PREFIX_SHOWN],
            key_hash=security.digest(token),
            created_by=created_by,
            allowed_models=allowed_models or None,
            rpm_limit=rpm_limit,
        )
        await self._audit.record(actor, "apikey.create", target=label, ip=ip, detail=key.prefix)
        return key, token

    async def authenticate(self, token: str | None) -> ApiPrincipal | None:
        """Return the principal for a valid, unrevoked token, else None."""
        if not token or not token.startswith(KEY_PREFIX) or len(token) > _MAX_TOKEN_LENGTH:
            return None
        key = await ApiKey.filter(key_hash=security.digest(token), revoked_at__isnull=True).first()
        if key is None:
            return None
        if monotonic() - self._last_touched.get(key.id, 0.0) > _TOUCH_INTERVAL_S:
            self._last_touched[key.id] = monotonic()
            await ApiKey.filter(id=key.id).update(last_used_at=datetime.now(UTC))
        return ApiPrincipal(key.id, key.label, key.allowed_models, key.rpm_limit)

    def enforce_rate_limit(self, principal: ApiPrincipal) -> None:
        """Raise ``RateLimitedError`` if the key exceeded its requests-per-minute budget."""
        if not principal.rpm_limit:
            return
        limiter = self._limiters.get(principal.id)
        if limiter is None or limiter.limit != principal.rpm_limit:
            limiter = self._limiters[principal.id] = security.SlidingWindowLimiter(
                principal.rpm_limit, 60
            )
        allowed, retry_after = limiter.check(str(principal.id))
        if not allowed:
            raise RateLimitedError(retry_after)

    async def page(
        self, *, q: str | None, status: KeyStatus | None, offset: int, limit: int
    ) -> tuple[list[ApiKey], int]:
        """One page of keys, newest first, with their creators loaded."""
        query = ApiKey.all()
        if q and q.strip():
            query = query.filter(label__icontains=q.strip())
        if status is not None:
            query = query.filter(revoked_at__isnull=status == "active")
        total = await query.count()
        rows = (
            await query.order_by("-created_at", "-id")
            .select_related("created_by")
            .offset(offset)
            .limit(limit)
        )
        return rows, total

    async def list_all(self) -> list[ApiKey]:
        """Every key, newest first, with its creator loaded."""
        return await ApiKey.all().order_by("-created_at").select_related("created_by")

    async def revoke(self, key_id: UUID, *, actor: str, ip: str | None) -> None:
        """Revoke a key. It stops working immediately."""
        key = await ApiKey.filter(id=key_id, revoked_at__isnull=True).first()
        if key is None:
            raise NotFoundError("key not found or already revoked")
        key.revoked_at = datetime.now(UTC)
        await key.save(update_fields=["revoked_at"])
        await self._audit.record(actor, "apikey.revoke", target=key.label, ip=ip)
