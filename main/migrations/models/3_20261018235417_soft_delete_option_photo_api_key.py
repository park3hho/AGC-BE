from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "api_key" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "name" VARCHAR(100) NOT NULL,
    "key_prefix" VARCHAR(16) NOT NULL,
    "key_hash" VARCHAR(64) NOT NULL UNIQUE,
    "active" BOOL NOT NULL,
    "last_used_at" TIMESTAMPTZ,
    "user_id" INT NOT NULL REFERENCES "app_user" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "api_key" IS '자동화용 API 키 (리서처 skill 등). 헤더 X-API-Key 로 받는다.';
        ALTER TABLE "product" ADD "deleted_at" TIMESTAMPTZ;
        ALTER TABLE "price_survey" ADD "deleted_at" TIMESTAMPTZ;
        ALTER TABLE "price_survey_option" ADD "photo_url" VARCHAR(1000);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "product" DROP COLUMN "deleted_at";
        ALTER TABLE "price_survey" DROP COLUMN "deleted_at";
        ALTER TABLE "price_survey_option" DROP COLUMN "photo_url";
        DROP TABLE IF EXISTS "api_key";"""


MODELS_STATE = (
    "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"
    "TIywdvXidqtrEwTYP01s0vZo//ACMKJcQ="
)
