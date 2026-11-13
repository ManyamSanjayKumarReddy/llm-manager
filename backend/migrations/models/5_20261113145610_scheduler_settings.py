from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "scheduler_settings" (
    "id" INT NOT NULL PRIMARY KEY,
    "queue_timeout_s" DOUBLE PRECISION NOT NULL,
    "wake_timeout_s" DOUBLE PRECISION NOT NULL,
    "sleep_timeout_s" DOUBLE PRECISION NOT NULL,
    "min_awake_s" DOUBLE PRECISION NOT NULL,
    "priority_hold_s" DOUBLE PRECISION NOT NULL,
    "preempt_after_s" DOUBLE PRECISION,
    "reaper_interval_s" DOUBLE PRECISION NOT NULL,
    "sleep_level" INT NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "updated_by" VARCHAR(64)
);
COMMENT ON TABLE "scheduler_settings" IS 'The wake/sleep scheduler''s timings, edited by admins. A single row (``id`` is always 1).';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "scheduler_settings";"""


MODELS_STATE = (
    "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"
    "qa9QLHiF4ovurP38P2ldGYE="
)
