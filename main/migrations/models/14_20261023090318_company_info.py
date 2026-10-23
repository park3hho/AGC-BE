from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "company_info" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "category" VARCHAR(30) NOT NULL,
    "name" VARCHAR(100) NOT NULL,
    "value" VARCHAR(500),
    "details" JSONB NOT NULL,
    "issuer" VARCHAR(100),
    "issued_on" DATE,
    "expires_on" DATE,
    "remind" BOOL NOT NULL,
    "url" VARCHAR(500),
    "link" VARCHAR(50),
    "sort" SMALLINT NOT NULL,
    "memo" TEXT,
    "deleted_at" TIMESTAMPTZ,
    "created_by_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL
);
COMMENT ON TABLE "company_info" IS '회사 정보 › 기본 정보 — 로그인도 비밀값도 아닌 회사 정보 1건 (사업자등록번호, 인허가 번호, 계좌, 연락처, 서류).';
        CREATE TABLE IF NOT EXISTS "company_info_file" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "path" VARCHAR(300) NOT NULL,
    "size" INT NOT NULL,
    "content_type" VARCHAR(50) NOT NULL,
    "info_id" INT NOT NULL REFERENCES "company_info" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "company_info_file" IS '기본 정보에 붙인 서류 파일 — PRIVATE_DIR 에 저장 (공개 /files 아님). 받기는 로그인한 account_view 만.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "company_info";
        DROP TABLE IF EXISTS "company_info_file";"""


MODELS_STATE = (
    "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"
    "+/n/PlOq1A=="
)
