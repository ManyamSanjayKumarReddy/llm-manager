"""Password hashing, token handling and rate limiting."""

import hashlib
import re
import secrets
import time
from collections import deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # argon2id, with the library's current recommended parameters

# Verified against when a username does not exist, so "unknown user" and "wrong password"
# take the same time (no account enumeration by timing).
DUMMY_HASH = _hasher.hash("not-a-real-password-used-only-for-timing")

USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_MAX_PASSWORD_LENGTH = 256
_MIN_DISTINCT_CHARS = 5
_MAX_TRACKED_KEYS = 10_000


def hash_password(password: str) -> str:
    """Hash a password with argon2id."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Check a password against its hash. Never raises."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash uses outdated parameters and should be recomputed on next login."""
    return _hasher.check_needs_rehash(password_hash)


def normalize_username(username: str) -> str:
    """Usernames are case-insensitive: store and compare them lowercase."""
    return username.strip().lower()


def password_problem(password: str, username: str, min_length: int) -> str | None:
    """Return why a password is unacceptable, or None if it is fine."""
    if len(password) < min_length:
        return f"password must be at least {min_length} characters"
    if len(password) > _MAX_PASSWORD_LENGTH:
        return "password is too long"
    if username and username.lower() in password.lower():
        return "password must not contain the username"
    if len(set(password)) < _MIN_DISTINCT_CHARS:
        return "password is too repetitive"
    return None


def new_token(prefix: str = "") -> str:
    """Return a URL-safe token with 256 bits of randomness."""
    return prefix + secrets.token_urlsafe(32)


def digest(token: str) -> str:
    """Hex SHA-256 of a token. Right for high-entropy random tokens, not for passwords."""
    return hashlib.sha256(token.encode()).hexdigest()


class SlidingWindowLimiter:
    """In-memory sliding-window rate limiter: ``limit`` hits per ``window_s`` per key."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> tuple[bool, int]:
        """Record a hit for ``key``. Returns ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return False, max(1, int(self.window_s - (now - hits[0])) + 1)
        hits.append(now)
        if len(self._hits) > _MAX_TRACKED_KEYS:
            self._drop_idle(now)
        return True, 0

    def _drop_idle(self, now: float) -> None:
        """Bound memory by forgetting keys with no recent hits."""
        idle = [k for k, v in self._hits.items() if not v or now - v[-1] > self.window_s]
        for key in idle:
            del self._hits[key]
