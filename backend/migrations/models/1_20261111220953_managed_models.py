from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "managed_models" (
    "id" UUID NOT NULL PRIMARY KEY,
    "name" VARCHAR(64) NOT NULL UNIQUE,
    "url" VARCHAR(300) NOT NULL,
    "served_name" VARCHAR(200),
    "gpus" JSONB NOT NULL,
    "idle_minutes" DOUBLE PRECISION NOT NULL,
    "priority" INT NOT NULL,
    "backend_api_key_env" VARCHAR(100),
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE "managed_models" IS 'A vLLM container the router manages. Registered from the dashboard.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "managed_models";"""


MODELS_STATE = (
    "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"
)
