"""The object graph shared by every request, stored on ``app.state``."""

from dataclasses import dataclass

import httpx

from llm_manager.core.settings import Settings
from llm_manager.engine import Manager
from llm_manager.services.api_keys import ApiKeyService
from llm_manager.services.audit import AuditService
from llm_manager.services.login import LoginService
from llm_manager.services.models import ModelService
from llm_manager.services.recorder import Recorder
from llm_manager.services.servers import ServerService
from llm_manager.services.sessions import SessionService
from llm_manager.services.stats import StatsService
from llm_manager.services.users import UserService


@dataclass
class Container:
    """Everything the routers need, built once at startup."""

    settings: Settings
    manager: Manager
    http: httpx.AsyncClient
    audit: AuditService
    sessions: SessionService
    login: LoginService
    users: UserService
    servers: ServerService
    models: ModelService
    api_keys: ApiKeyService
    stats: StatsService
    recorder: Recorder


def build_container(settings: Settings, manager: Manager, http: httpx.AsyncClient) -> Container:
    """Wire the services together."""
    audit = AuditService()
    sessions = SessionService(settings)
    return Container(
        settings=settings,
        manager=manager,
        http=http,
        audit=audit,
        sessions=sessions,
        login=LoginService(settings, sessions, audit),
        users=UserService(settings, audit, sessions),
        servers=ServerService(audit),
        models=ModelService(manager, audit, http),
        api_keys=ApiKeyService(audit),
        stats=StatsService(),
        recorder=Recorder(),
    )
