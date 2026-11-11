# Wakeful backend

The API and scheduler behind Wakeful: FastAPI, Tortoise ORM (PostgreSQL), Pydantic, Aerich migrations, managed with uv.

See the [main README](../README.md) for what it does, how to run it, and the security model.

```bash
uv sync                          # install the locked dependencies
uv run aerich upgrade            # create or update the tables
uv run llm-manager --help        # create-user, reset-password, unlock-user, list-users, create-api-key
uv run uvicorn llm_manager.main:app_from_env --factory --port 8000
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                    # needs Docker (a throw-away PostgreSQL) or TEST_DATABASE_URL
```
