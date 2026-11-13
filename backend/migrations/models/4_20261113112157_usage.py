from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "usage_daily" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "day" DATE NOT NULL,
    "api_key_id" UUID NOT NULL,
    "model" VARCHAR(100) NOT NULL,
    "requests" BIGINT NOT NULL,
    "errors" BIGINT NOT NULL,
    "prompt_tokens" BIGINT NOT NULL,
    "completion_tokens" BIGINT NOT NULL,
    CONSTRAINT "uid_usage_daily_day_db0434" UNIQUE ("day", "api_key_id", "model")
);
CREATE INDEX IF NOT EXISTS "idx_usage_daily_day_9afe60" ON "usage_daily" ("day");
CREATE INDEX IF NOT EXISTS "idx_usage_daily_api_key_dba727" ON "usage_daily" ("api_key_id");
COMMENT ON TABLE "usage_daily" IS 'Requests and tokens per day, API key and model. Outlives the request log.';
        ALTER TABLE "request_log" ADD "prompt_tokens" INT NOT NULL DEFAULT 0;
        ALTER TABLE "request_log" ADD "completion_tokens" INT NOT NULL DEFAULT 0;
        -- keep the request history that already exists (tokens were not recorded before)
        INSERT INTO "usage_daily" ("day", "api_key_id", "model", "requests", "errors", "prompt_tokens", "completion_tokens")
        SELECT (ts AT TIME ZONE 'UTC')::date, api_key_id, model, COUNT(*), COUNT(*) FILTER (WHERE status >= 400), 0, 0
        FROM "request_log" WHERE api_key_id IS NOT NULL
        GROUP BY 1, 2, 3;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "request_log" DROP COLUMN "prompt_tokens";
        ALTER TABLE "request_log" DROP COLUMN "completion_tokens";
        DROP TABLE IF EXISTS "usage_daily";"""


MODELS_STATE = (
    "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"
)
