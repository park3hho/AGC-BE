"""옵션 구조 정규화 (2026-11-18) — 제품 단위 고정 옵션 product_option + 조사별 가격 기록 price_survey_price.

- price_survey_option 을 product_option 으로 이름만 바꾼다 → id 가 그대로라 option_price · product_bundle ·
  product_pricing.base_option · competitor_price 의 FK 와 마켓 SKU / 주문 seller_code / market_listing.items.option_id 가 그대로 산다.
- product_id 를 조사에서 채우고 survey_id 는 뺀다. 조사별 가격은 price_survey_price 로 옮긴다 (옵션마다 1줄 = 지금 조사).
- 지운 조사의 옵션은 deleted_at 을 조사 삭제 시각으로 (예전에도 화면에 안 보이던 것).
- 같은 제품 안 같은 옵션(공백·대소문자 무시) 중복 방지, 묶음·경쟁가의 product_id 가 옵션의 제품과 같도록 복합 FK,
  option_price (pricing, option, bundle_qty) UNIQUE (모델엔 있었지만 DB 에 없던 것).
- product_pricing.survey_id FK 를 CASCADE → RESTRICT (조사 하드 삭제가 가격 책정·판매가를 통째로 지우던 위험 차단).
- 마지막 DO 블록이 개수를 확인하고 어긋나면 예외 → 트랜잭션 전체 롤백.
"""
from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return r"""
        ALTER TABLE "price_survey_option" RENAME TO "product_option";
        ALTER SEQUENCE IF EXISTS "price_survey_option_id_seq" RENAME TO "product_option_id_seq";
        ALTER INDEX IF EXISTS "price_survey_option_pkey" RENAME TO "product_option_pkey";

        ALTER TABLE "product_option" ADD "product_id" INT;
        UPDATE "product_option" o SET "product_id" = s."product_id" FROM "price_survey" s WHERE s."id" = o."survey_id";
        ALTER TABLE "product_option" ALTER COLUMN "product_id" SET NOT NULL;
        ALTER TABLE "product_option" ADD CONSTRAINT "fk_product__product_bb21a3f2" FOREIGN KEY ("product_id") REFERENCES "product" ("id") ON DELETE CASCADE;
        ALTER TABLE "product_option" ADD "sort" SMALLINT NOT NULL DEFAULT 0;
        ALTER TABLE "product_option" ADD "deleted_at" TIMESTAMPTZ;
        UPDATE "product_option" o SET "deleted_at" = s."deleted_at" FROM "price_survey" s
         WHERE s."id" = o."survey_id" AND s."deleted_at" IS NOT NULL;

        CREATE TABLE IF NOT EXISTS "price_survey_price" (
            "id" SERIAL NOT NULL PRIMARY KEY,
            "created_at" TIMESTAMPTZ NOT NULL,
            "updated_at" TIMESTAMPTZ NOT NULL,
            "price_cny" DECIMAL(12,2) NOT NULL,
            "option_id" INT NOT NULL REFERENCES "product_option" ("id") ON DELETE CASCADE,
            "survey_id" INT NOT NULL REFERENCES "price_survey" ("id") ON DELETE CASCADE,
            CONSTRAINT "uid_price_surve_survey__847106" UNIQUE ("survey_id", "option_id")
        );
        INSERT INTO "price_survey_price" ("created_at", "updated_at", "survey_id", "option_id", "price_cny")
        SELECT "created_at", "updated_at", "survey_id", "id", "price_cny" FROM "product_option" ORDER BY "id";
        CREATE INDEX IF NOT EXISTS "idx_price_surve_option__optnorm" ON "price_survey_price" ("option_id");

        ALTER TABLE "product_option" DROP CONSTRAINT IF EXISTS "price_survey_option_survey_id_fkey";
        ALTER TABLE "product_option" DROP COLUMN "survey_id";
        CREATE INDEX IF NOT EXISTS "idx_product_opt_product_optnorm" ON "product_option" ("product_id");
        CREATE UNIQUE INDEX IF NOT EXISTS "uidx_product_opt_key_optnorm" ON "product_option" (
            "product_id",
            lower(regexp_replace("option1", '\s', '', 'g')),
            lower(regexp_replace(coalesce("option2", ''), '\s', '', 'g'))
        ) WHERE "deleted_at" IS NULL;

        ALTER TABLE "product_option" ADD CONSTRAINT "uid_product_opt_id_product_optnorm" UNIQUE ("id", "product_id");
        ALTER TABLE "product_bundle" ADD CONSTRAINT "fk_product_bun_same_product_optnorm"
            FOREIGN KEY ("option_id", "product_id") REFERENCES "product_option" ("id", "product_id") ON DELETE CASCADE;
        ALTER TABLE "competitor_price" ADD CONSTRAINT "fk_competitor_same_product_optnorm"
            FOREIGN KEY ("option_id", "product_id") REFERENCES "product_option" ("id", "product_id") ON DELETE SET NULL ("option_id");
        ALTER TABLE "option_price" ADD CONSTRAINT "uid_option_pric_pricing_optnorm" UNIQUE ("pricing_id", "option_id", "bundle_qty");
        ALTER TABLE "product_pricing" DROP CONSTRAINT IF EXISTS "product_pricing_survey_id_fkey";
        ALTER TABLE "product_pricing" ADD CONSTRAINT "product_pricing_survey_id_fkey"
            FOREIGN KEY ("survey_id") REFERENCES "price_survey" ("id") ON DELETE RESTRICT;

        COMMENT ON TABLE "product_option" IS '제품 옵션 1개 (맛 × 용량·입수) — 제품 단위로 고정된 판매 옵션의 뿌리 (2026-11-18 옵션 구조 정규화).';
        COMMENT ON TABLE "price_survey_price" IS '가격 조사 1건에서 본 옵션 1개의 가격 (관찰 기록). 조사 1 : N, 제품 옵션 1 : N (조사할 때마다 1줄).';

        DO $$
        BEGIN
            IF (SELECT count(*) FROM "price_survey_price") <> (SELECT count(*) FROM "product_option") THEN
                RAISE EXCEPTION 'optnorm: price_survey_price 개수가 product_option 과 다름';
            END IF;
            IF EXISTS (SELECT 1 FROM "product_option" o JOIN "price_survey_price" p ON p."option_id" = o."id"
                       WHERE p."price_cny" <> o."price_cny") THEN
                RAISE EXCEPTION 'optnorm: 가격 복사 불일치';
            END IF;
            IF EXISTS (SELECT 1 FROM "option_price" op JOIN "product_pricing" pp ON pp."id" = op."pricing_id"
                       JOIN "product_option" o ON o."id" = op."option_id" WHERE o."product_id" <> pp."product_id") THEN
                RAISE EXCEPTION 'optnorm: 판매가 옵션의 제품이 가격 책정 제품과 다름';
            END IF;
        END $$;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return r"""
        ALTER TABLE "option_price" DROP CONSTRAINT IF EXISTS "uid_option_pric_pricing_optnorm";
        ALTER TABLE "product_pricing" DROP CONSTRAINT IF EXISTS "product_pricing_survey_id_fkey";
        ALTER TABLE "product_pricing" ADD CONSTRAINT "product_pricing_survey_id_fkey"
            FOREIGN KEY ("survey_id") REFERENCES "price_survey" ("id") ON DELETE CASCADE;
        ALTER TABLE "competitor_price" DROP CONSTRAINT IF EXISTS "fk_competitor_same_product_optnorm";
        ALTER TABLE "product_bundle" DROP CONSTRAINT IF EXISTS "fk_product_bun_same_product_optnorm";
        ALTER TABLE "product_option" DROP CONSTRAINT IF EXISTS "uid_product_opt_id_product_optnorm";
        DROP INDEX IF EXISTS "uidx_product_opt_key_optnorm";
        DROP INDEX IF EXISTS "idx_product_opt_product_optnorm";
        ALTER TABLE "product_option" ADD "survey_id" INT;
        UPDATE "product_option" o SET "survey_id" = x."survey_id", "price_cny" = x."price_cny" FROM (
            SELECT DISTINCT ON (p."option_id") p."option_id", p."survey_id", p."price_cny"
            FROM "price_survey_price" p JOIN "price_survey" s ON s."id" = p."survey_id"
            ORDER BY p."option_id", s."survey_date" DESC, s."id" DESC
        ) x WHERE x."option_id" = o."id";
        DELETE FROM "product_option" WHERE "survey_id" IS NULL;
        ALTER TABLE "product_option" ALTER COLUMN "survey_id" SET NOT NULL;
        ALTER TABLE "product_option" ADD CONSTRAINT "price_survey_option_survey_id_fkey" FOREIGN KEY ("survey_id") REFERENCES "price_survey" ("id") ON DELETE CASCADE;
        DROP TABLE IF EXISTS "price_survey_price";
        ALTER TABLE "product_option" DROP CONSTRAINT IF EXISTS "fk_product__product_bb21a3f2";
        ALTER TABLE "product_option" DROP COLUMN "product_id";
        ALTER TABLE "product_option" DROP COLUMN "sort";
        ALTER TABLE "product_option" DROP COLUMN "deleted_at";
        ALTER INDEX IF EXISTS "product_option_pkey" RENAME TO "price_survey_option_pkey";
        ALTER SEQUENCE IF EXISTS "product_option_id_seq" RENAME TO "price_survey_option_id_seq";
        ALTER TABLE "product_option" RENAME TO "price_survey_option";"""


MODELS_STATE = (
    "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"
    "RM9p+L+Dp7o61lHdbYG21/Mfvx/wGtZL8l"
)
