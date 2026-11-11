from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "audit_log" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "ts" TIMESTAMPTZ NOT NULL,
    "actor" VARCHAR(100) NOT NULL,
    "action" VARCHAR(60) NOT NULL,
    "target" VARCHAR(200),
    "ip" VARCHAR(64),
    "detail" TEXT
);
CREATE INDEX IF NOT EXISTS "idx_audit_log_ts_47137a" ON "audit_log" ("ts");
COMMENT ON TABLE "audit_log" IS 'Who did what: logins, user changes, API key changes.';
CREATE TABLE IF NOT EXISTS "events" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "ts" TIMESTAMPTZ NOT NULL,
    "model" VARCHAR(100),
    "kind" VARCHAR(40) NOT NULL,
    "detail" TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS "idx_events_ts_9388cd" ON "events" ("ts");
COMMENT ON TABLE "events" IS 'A wake/sleep/failure event of the router.';
CREATE TABLE IF NOT EXISTS "users" (
    "id" UUID NOT NULL PRIMARY KEY,
    "username" VARCHAR(64) NOT NULL UNIQUE,
    "password_hash" TEXT NOT NULL,
    "role" VARCHAR(16) NOT NULL,
    "is_active" BOOL NOT NULL,
    "failed_attempts" INT NOT NULL,
    "locked_until" TIMESTAMPTZ,
    "created_at" TIMESTAMPTZ NOT NULL,
    "last_login_at" TIMESTAMPTZ,
    "password_changed_at" TIMESTAMPTZ NOT NULL
);
COMMENT ON COLUMN "users"."role" IS 'ADMIN: admin\nVIEWER: viewer';
COMMENT ON TABLE "users" IS 'A person who may log in to the dashboard. Created by an admin; no self-registration.';
CREATE TABLE IF NOT EXISTS "api_keys" (
    "id" UUID NOT NULL PRIMARY KEY,
    "label" VARCHAR(100) NOT NULL,
    "prefix" VARCHAR(16) NOT NULL,
    "key_hash" VARCHAR(64) NOT NULL UNIQUE,
    "created_at" TIMESTAMPTZ NOT NULL,
    "last_used_at" TIMESTAMPTZ,
    "revoked_at" TIMESTAMPTZ,
    "allowed_models" JSONB,
    "rpm_limit" INT,
    "created_by_id" UUID REFERENCES "users" ("id") ON DELETE SET NULL
);
COMMENT ON TABLE "api_keys" IS 'A credential for programs calling ``/v1/*``.';
CREATE TABLE IF NOT EXISTS "request_log" (
    "id" BIGSERIAL NOT NULL PRIMARY KEY,
    "ts" TIMESTAMPTZ NOT NULL,
    "model" VARCHAR(100) NOT NULL,
    "status" INT NOT NULL,
    "duration_ms" INT NOT NULL,
    "queue_wait_ms" INT NOT NULL,
    "api_key_id" UUID REFERENCES "api_keys" ("id") ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS "idx_request_log_ts_08a0fe" ON "request_log" ("ts");
CREATE INDEX IF NOT EXISTS "idx_request_log_model_10685d" ON "request_log" ("model", "ts");
COMMENT ON TABLE "request_log" IS 'One proxied request (no prompts or responses are stored).';
CREATE TABLE IF NOT EXISTS "sessions" (
    "id" UUID NOT NULL PRIMARY KEY,
    "token_hash" VARCHAR(64) NOT NULL UNIQUE,
    "csrf_token" VARCHAR(64) NOT NULL,
    "created_at" TIMESTAMPTZ NOT NULL,
    "last_seen_at" TIMESTAMPTZ NOT NULL,
    "expires_at" TIMESTAMPTZ NOT NULL,
    "ip" VARCHAR(64),
    "user_agent" VARCHAR(300),
    "user_id" UUID NOT NULL REFERENCES "users" ("id") ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_sessions_expires_6bcc94" ON "sessions" ("expires_at");
COMMENT ON TABLE "sessions" IS 'A browser login session.';
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSONB NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """


MODELS_STATE = (
    "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"
)
