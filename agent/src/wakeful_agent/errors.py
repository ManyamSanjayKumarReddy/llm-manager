"""Errors the agent turns into clear HTTP answers."""


class AgentError(Exception):
    """Something the caller can understand and fix; ``status`` is the HTTP code to answer with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class NotFoundError(AgentError):
    """No container with that name that this agent manages."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no container called '{name}' is managed by this agent", 404)


class SpecError(AgentError):
    """The requested container breaks one of the agent's safety rules."""

    def __init__(self, message: str) -> None:
        super().__init__(message, 422)
