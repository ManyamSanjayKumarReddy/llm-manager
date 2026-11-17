from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "managed_models" ADD "container_name" VARCHAR(64);
        ALTER TABLE "servers" ADD "agent_url" VARCHAR(300);
        ALTER TABLE "servers" ADD "agent_token" TEXT;
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_managed_mod_server__e8cc0c" ON "managed_models" ("server_id", "container_name");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "uid_managed_mod_server__e8cc0c";
        ALTER TABLE "servers" DROP COLUMN "agent_url";
        ALTER TABLE "servers" DROP COLUMN "agent_token";
        ALTER TABLE "managed_models" DROP COLUMN "container_name";"""


MODELS_STATE = (
    "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"
    "bNr7K+6M7az/8DOViE6A=="
)
