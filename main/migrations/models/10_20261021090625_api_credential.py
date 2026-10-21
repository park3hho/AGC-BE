from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "api_credential" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "service" VARCHAR(100) NOT NULL,
    "url" VARCHAR(500),
    "public_values" JSONB NOT NULL,
    "issued_on" DATE,
    "expires_on" DATE,
    "reauth_from" DATE,
    "reauth_to" DATE,
    "allowed_ips" JSONB NOT NULL,
    "memo" TEXT,
    "deleted_at" TIMESTAMPTZ,
    "created_by_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL
);
COMMENT ON TABLE "api_credential" IS '회사가 쓰는 외부 API 키 묶음 (네이버 커머스API · 쿠팡 OpenAPI 등). 로그인 계정(CompanyAccount)과 따로 둔다.';
        CREATE TABLE IF NOT EXISTS "api_credential_secret" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "label" VARCHAR(50) NOT NULL,
    "value_enc" TEXT NOT NULL,
    "sort" SMALLINT NOT NULL,
    "credential_id" INT NOT NULL REFERENCES "api_credential" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "api_credential_secret" IS '비밀값 1개 (시크릿·Access Key·Secret Key 등). 값은 Fernet 암호문 — 목록·로그 노출 금지.';
        CREATE TABLE IF NOT EXISTS "api_credential_secret_view" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "ip" VARCHAR(64),
    "secret_id" INT NOT NULL REFERENCES "api_credential_secret" ("id") ON DELETE CASCADE,
    "user_id" INT NOT NULL REFERENCES "app_user" ("id") ON DELETE RESTRICT
);
COMMENT ON TABLE "api_credential_secret_view" IS '비밀값 열람 기록 — 누가, 언제(created_at), 어느 비밀값을 봤는지. 지우지 않는다.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "api_credential";
        DROP TABLE IF EXISTS "api_credential_secret";
        DROP TABLE IF EXISTS "api_credential_secret_view";"""


MODELS_STATE = (
    "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"
    "7aY="
)
