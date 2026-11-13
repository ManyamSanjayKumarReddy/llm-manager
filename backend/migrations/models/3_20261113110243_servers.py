import json
import uuid

from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    await db.execute_script(
        """
        CREATE TABLE IF NOT EXISTS "servers" (
    "id" UUID NOT NULL PRIMARY KEY,
    "name" VARCHAR(64) NOT NULL UNIQUE,
    "gpu_count" INT NOT NULL,
    "gpu_type" VARCHAR(100),
    "created_at" TIMESTAMPTZ NOT NULL
);
COMMENT ON TABLE "servers" IS 'A machine with GPUs that runs vLLM containers. Models are placed on one.';
        ALTER TABLE "managed_models" ADD "server_id" UUID;"""
    )
    # Models registered before servers existed all go on one server, big enough for the GPU
    # numbers they use. Move them to the right servers from the dashboard afterwards.
    models = await db.execute_query_dict('SELECT "id", "gpus" FROM "managed_models"')
    if models:
        server_id = uuid.uuid4()
        count = 1
        for row in models:
            gpus = json.loads(row["gpus"]) if isinstance(row["gpus"], str) else row["gpus"]
            count = max(count, max(gpus, default=0) + 1)
        await db.execute_query(
            'INSERT INTO "servers" ("id", "name", "gpu_count", "created_at") '
            "VALUES ($1, 'this-server', $2, NOW())",
            [server_id, count],
        )
        await db.execute_query('UPDATE "managed_models" SET "server_id" = $1', [server_id])
    return """
        ALTER TABLE "managed_models" ALTER COLUMN "server_id" SET NOT NULL;
        ALTER TABLE "managed_models" ADD CONSTRAINT "fk_managed__servers_279ba019" FOREIGN KEY ("server_id") REFERENCES "servers" ("id") ON DELETE RESTRICT;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "managed_models" DROP CONSTRAINT IF EXISTS "fk_managed__servers_279ba019";
        ALTER TABLE "managed_models" DROP COLUMN "server_id";
        DROP TABLE IF EXISTS "servers";"""


MODELS_STATE = (
    "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"
)
