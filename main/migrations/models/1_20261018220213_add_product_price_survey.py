from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "product" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "code" VARCHAR(50) NOT NULL UNIQUE,
    "photo_url" VARCHAR(1000),
    "title_cn" VARCHAR(300) NOT NULL,
    "title_ko" VARCHAR(300)
);
COMMENT ON TABLE "product" IS '제품 — 판매할 상품 1건. 제품 코드 추가일 = created_at.';
        CREATE TABLE IF NOT EXISTS "price_survey" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "code" VARCHAR(50) NOT NULL UNIQUE,
    "survey_date" DATE NOT NULL,
    "photo_url" VARCHAR(1000),
    "taobao_url" VARCHAR(1000) NOT NULL,
    "coupang_min_price" INT,
    "coupang_url" VARCHAR(1000),
    "naver_min_price" INT,
    "naver_url" VARCHAR(1000),
    "product_id" INT NOT NULL REFERENCES "product" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "price_survey" IS '가격 조사 — 제품 1개를 특정 날짜에 조사한 기록. 제품 1 : 조사 N.';
        CREATE TABLE IF NOT EXISTS "price_survey_option" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "option1" VARCHAR(200) NOT NULL,
    "option2" VARCHAR(200),
    "price_cny" DECIMAL(12,2) NOT NULL,
    "survey_id" INT NOT NULL REFERENCES "price_survey" ("id") ON DELETE CASCADE
);
COMMENT ON TABLE "price_survey_option" IS '조사한 옵션 1개 조합 + 그 가격. 예) 옵션1=색상 ''검정'', 옵션2=사이즈 ''L'', 39.90 위안.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "product";
        DROP TABLE IF EXISTS "price_survey_option";
        DROP TABLE IF EXISTS "price_survey";"""


MODELS_STATE = (
    "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"
    "0="
)
