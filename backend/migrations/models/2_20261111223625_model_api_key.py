from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "managed_models" ADD "backend_api_key" TEXT;
        ALTER TABLE "managed_models" DROP COLUMN "backend_api_key_env";"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "managed_models" ADD "backend_api_key_env" VARCHAR(100);
        ALTER TABLE "managed_models" DROP COLUMN "backend_api_key";"""


MODELS_STATE = (
    "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"
    "LeTtPKnbvNk3M4RUmssZSl7O8KLHLb//Dx3C058="
)
