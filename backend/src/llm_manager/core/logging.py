"""Logging setup. Secrets (passwords, tokens, API keys) are never logged."""

import logging

# The database driver's debug log prints every query with its parameters, which would include
# password hashes and stored API keys. It stays off whatever level the application logs at.
_SQL_LOGGERS = ("tortoise.db_client", "tortoise.backends", "asyncpg")


def keep_query_parameters_out_of_logs() -> None:
    """Make sure SQL text with parameter values can never be written to the log."""
    for name in _SQL_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(level: str) -> None:
    """Send logs to stderr in a single readable format."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # httpx logs every request URL at INFO: too chatty and not useful here.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    keep_query_parameters_out_of_logs()
