"""Entry point: ``uvicorn wakeful_agent.main:app_from_env --factory`` (see the README)."""

import logging

from fastapi import FastAPI

from wakeful_agent.app import create_app
from wakeful_agent.docker import CliDocker
from wakeful_agent.host import HostInfo
from wakeful_agent.settings import Settings


def app_from_env() -> FastAPI:
    """Build the agent from ``AGENT_*`` environment variables."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    return create_app(settings, CliDocker(settings), HostInfo(settings))
