from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "app_user" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "username" VARCHAR(50) NOT NULL UNIQUE,
    "name" VARCHAR(50) NOT NULL,
    "password_hash" VARCHAR(100) NOT NULL,
    "role" VARCHAR(20) NOT NULL,
    "active" BOOL NOT NULL,
    "session_version" INT NOT NULL
);
COMMENT ON TABLE "app_user" IS '로그인 계정 (사람). 역할은 core.permissions.Role 값.';
        CREATE TABLE IF NOT EXISTS "company_account" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "platform" VARCHAR(100) NOT NULL,
    "login_id" VARCHAR(200) NOT NULL,
    "password_enc" TEXT NOT NULL,
    "usages" JSONB NOT NULL,
    "created_by_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL
);
COMMENT ON TABLE "company_account" IS '회사가 쓰는 외부 서비스 계정 (타오바오·쿠팡·네이버 등).';
        CREATE TABLE IF NOT EXISTS "company_account_password_view" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "ip" VARCHAR(64),
    "account_id" INT NOT NULL REFERENCES "company_account" ("id") ON DELETE CASCADE,
    "user_id" INT NOT NULL REFERENCES "app_user" ("id") ON DELETE RESTRICT
);
COMMENT ON TABLE "company_account_password_view" IS '비밀번호 열람 기록 — 누가, 언제(created_at), 어느 계정을 봤는지. 지우지 않는다.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "app_user";
        DROP TABLE IF EXISTS "company_account";
        DROP TABLE IF EXISTS "company_account_password_view";"""


MODELS_STATE = (
    "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"
    "7JptbJumQerm5m9mj/8HhDQwMg=="
)
