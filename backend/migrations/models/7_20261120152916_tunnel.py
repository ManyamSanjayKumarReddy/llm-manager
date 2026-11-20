from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "servers" ADD "tunnel_last_seen" TIMESTAMPTZ;
        ALTER TABLE "servers" ADD "tunnel_token_hash" VARCHAR(64) UNIQUE;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "uid_servers_tunnel__9ec917";
        ALTER TABLE "servers" DROP COLUMN "tunnel_last_seen";
        ALTER TABLE "servers" DROP COLUMN "tunnel_token_hash";"""


MODELS_STATE = (
    "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"
)
