"""Administration commands: bootstrap the first admin, reset passwords, create API keys.

Run from the ``backend`` folder, for example::

    uv run llm-manager create-user --username alice --role admin
"""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Awaitable, Callable

from tortoise import Tortoise

from llm_manager.core.errors import DomainError
from llm_manager.core.settings import get_settings
from llm_manager.db.config import build_tortoise_config
from llm_manager.db.models import Role, User
from llm_manager.services.api_keys import ApiKeyService
from llm_manager.services.audit import AuditService
from llm_manager.services.sessions import SessionService
from llm_manager.services.users import UserService

_ACTOR = "cli"


def _read_password(args: argparse.Namespace) -> str:
    """Read a new password from stdin (for scripts) or prompt twice."""
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat password: "):
        raise SystemExit("passwords do not match")
    return first


def _user_service() -> UserService:
    settings = get_settings()
    return UserService(settings, AuditService(), SessionService(settings))


async def _create_user(args: argparse.Namespace) -> None:
    user = await _user_service().create(
        args.username, _read_password(args), Role(args.role), actor=_ACTOR
    )
    print(f"created {user.role.value} '{user.username}'")


async def _reset_password(args: argparse.Namespace) -> None:
    user = await User.get_or_none(username=args.username.strip().lower())
    if user is None:
        raise SystemExit("no such user")
    await _user_service().reset_password(user.id, _read_password(args), actor=_ACTOR, ip=None)
    print(f"password changed for '{user.username}'; their sessions were ended")


async def _unlock(args: argparse.Namespace) -> None:
    found = await _user_service().unlock(args.username, actor=_ACTOR)
    print("unlocked" if found else "no such user")


async def _list_users(_: argparse.Namespace) -> None:
    for user in await _user_service().list_all():
        state = "active" if user.is_active else "DISABLED"
        print(f"{user.username:<24} {user.role.value:<7} {state}")


async def _create_api_key(args: argparse.Namespace) -> None:
    key, token = await ApiKeyService(AuditService()).create(
        args.label,
        created_by=None,
        allowed_models=args.models or None,
        rpm_limit=args.rpm,
        actor=_ACTOR,
    )
    print(f"API key '{key.label}' (shown once, store it now):\n{token}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-manager", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    def add(
        name: str, handler: Callable[[argparse.Namespace], Awaitable[None]], help_: str
    ) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_)
        sub.set_defaults(handler=handler)
        return sub

    create = add("create-user", _create_user, "create a dashboard account")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=[r.value for r in Role], default=Role.VIEWER.value)
    create.add_argument(
        "--password-stdin", action="store_true", help="read the password from stdin"
    )

    reset = add("reset-password", _reset_password, "set a new password (ends their sessions)")
    reset.add_argument("--username", required=True)
    reset.add_argument("--password-stdin", action="store_true")

    unlock = add("unlock-user", _unlock, "clear a login lockout")
    unlock.add_argument("--username", required=True)

    add("list-users", _list_users, "list accounts")

    key = add("create-api-key", _create_api_key, "create an API key for /v1/*")
    key.add_argument("--label", required=True)
    key.add_argument("--models", nargs="*", help="restrict to these models (default: all)")
    key.add_argument("--rpm", type=int, help="requests per minute limit (default: unlimited)")
    return parser


async def _run(args: argparse.Namespace) -> None:
    await Tortoise.init(config=build_tortoise_config(get_settings().database_url))
    try:
        await args.handler(args)
    finally:
        await Tortoise.close_connections()


def main() -> None:
    """Console-script entry point."""
    args = _parser().parse_args()
    try:
        asyncio.run(_run(args))
    except DomainError as exc:
        raise SystemExit(f"error: {exc}") from None
