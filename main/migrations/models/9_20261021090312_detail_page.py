from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "detail_page" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "content" JSONB NOT NULL,
    "status" VARCHAR(20) NOT NULL,
    "reviewed_at" TIMESTAMPTZ,
    "review_note" TEXT,
    "review_checks" JSONB,
    "reviewed_by_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL,
    "updated_by_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL,
    "product_id" INT NOT NULL UNIQUE REFERENCES "product" ("id") ON DELETE CASCADE
);
COMMENT ON COLUMN "detail_page"."status" IS 'DRAFT: draft\nREVIEW: review\nAPPROVED: approved\nCHANGES: changes';
COMMENT ON TABLE "detail_page" IS '상세페이지 — 제품 1개 : 1개. S1~S5 문구·사진은 content(JSON), S6 공통 안내·등록번호는 DetailPageCommon.';
        CREATE TABLE IF NOT EXISTS "detail_page_common" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "reg_no" VARCHAR(50) NOT NULL,
    "seller" VARCHAR(100) NOT NULL,
    "notice_title" VARCHAR(100) NOT NULL,
    "notice" JSONB NOT NULL,
    "updated_by_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL
);
COMMENT ON TABLE "detail_page_common" IS '모든 상세페이지가 같이 쓰는 S6 해외구매대행 안내 + 등록번호. 행 1개 (id=1).';
        CREATE TABLE IF NOT EXISTS "detail_page_review" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "action" VARCHAR(20) NOT NULL,
    "note" TEXT,
    "checks" JSONB,
    "page_id" INT NOT NULL REFERENCES "detail_page" ("id") ON DELETE CASCADE,
    "user_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL
);
COMMENT ON COLUMN "detail_page_review"."action" IS 'SUBMIT: submit\nAPPROVE: approve\nCHANGES: changes\nRESET: reset';
COMMENT ON TABLE "detail_page_review" IS '검수 기록 — 검수 요청 · 승인 · 수정 요청 · 자동 되돌림. 지우지 않는다.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "detail_page_common";
        DROP TABLE IF EXISTS "detail_page";
        DROP TABLE IF EXISTS "detail_page_review";"""


MODELS_STATE = (
    "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"
    "ZzjVFONq7HzZ/mD2/f+gG2EU"
)
