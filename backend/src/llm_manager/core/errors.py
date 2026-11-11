"""Domain errors. The API layer maps each of these to an HTTP response."""


class DomainError(Exception):
    """Base class for all expected, user-facing failures."""


class AuthenticationError(DomainError):
    """Wrong credentials, or a locked/disabled account.

    Deliberately carries no detail, so callers cannot tell which case occurred.
    """


class RateLimitedError(DomainError):
    """Too many requests; the caller should retry after ``retry_after`` seconds."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class InvalidInputError(DomainError):
    """The request is well-formed but not acceptable (weak password, duplicate name, ...)."""


class NotFoundError(DomainError):
    """The referenced object does not exist."""


class UnavailableError(DomainError):
    """A model cannot serve the request right now (maps to HTTP 503 + Retry-After)."""

    def __init__(self, message: str, retry_after: int = 5) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class UnknownModelError(DomainError):
    """The requested model name is not configured."""
