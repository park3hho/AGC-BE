from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "market_order" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "market" VARCHAR(10) NOT NULL,
    "line_no" VARCHAR(60) NOT NULL,
    "order_no" VARCHAR(40) NOT NULL,
    "ship_unit_no" VARCHAR(40) NOT NULL,
    "market_status" VARCHAR(40) NOT NULL,
    "confirmed" BOOL NOT NULL,
    "stage" VARCHAR(20) NOT NULL,
    "ordered_at" TIMESTAMPTZ,
    "paid_at" TIMESTAMPTZ,
    "ship_due_at" TIMESTAMPTZ,
    "product_name" VARCHAR(300) NOT NULL,
    "option_name" VARCHAR(300),
    "seller_code" VARCHAR(100),
    "market_product_id" VARCHAR(40),
    "market_option_id" VARCHAR(40),
    "quantity" INT NOT NULL,
    "unit_price" INT,
    "total_price" INT,
    "receiver_name" VARCHAR(100),
    "receiver_phone_enc" TEXT,
    "receiver_zip" VARCHAR(10),
    "receiver_address_enc" TEXT,
    "pccc_enc" TEXT,
    "pccc_status" VARCHAR(20) NOT NULL,
    "pccc_message" TEXT,
    "pccc_checked_at" TIMESTAMPTZ,
    "pccc_valid_to" DATE,
    "receiver_hash" VARCHAR(64),
    "raw_enc" TEXT,
    "last_synced_at" TIMESTAMPTZ,
    CONSTRAINT "uid_market_orde_market_454bae" UNIQUE ("market", "line_no")
);
COMMENT ON TABLE "market_order" IS '마켓(네이버·쿠팡) 주문 1줄 = 상품 주문 1개.';
        CREATE TABLE IF NOT EXISTS "order_sync_run" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "market" VARCHAR(10) NOT NULL,
    "trigger" VARCHAR(20) NOT NULL,
    "range_from" TIMESTAMPTZ NOT NULL,
    "range_to" TIMESTAMPTZ NOT NULL,
    "finished_at" TIMESTAMPTZ,
    "fetched" INT NOT NULL,
    "created" INT NOT NULL,
    "changed" INT NOT NULL,
    "checked" INT NOT NULL,
    "ok" BOOL,
    "error" TEXT,
    "actor_user_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL
);
COMMENT ON TABLE "order_sync_run" IS '주문 수집 1번 — 언제 누가(폴링·수동) 어느 구간을 받아 몇 건이 새로 들어오고 바뀌었는지.';
        CREATE TABLE IF NOT EXISTS "order_event" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "actor_type" VARCHAR(10) NOT NULL,
    "via" VARCHAR(20) NOT NULL,
    "kind" VARCHAR(30) NOT NULL,
    "summary" VARCHAR(300) NOT NULL,
    "data" JSONB NOT NULL,
    "actor_user_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL,
    "order_id" INT REFERENCES "market_order" ("id") ON DELETE RESTRICT,
    "sync_run_id" INT REFERENCES "order_sync_run" ("id") ON DELETE SET NULL
);
COMMENT ON TABLE "order_event" IS '주문 추적 기록 — 누가(시스템·에이전트·사람) 무엇을 했고 어떤 값을 보내고 받았는지. 지우지도 고치지도 않는다.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "order_sync_run";
        DROP TABLE IF EXISTS "market_order";
        DROP TABLE IF EXISTS "order_event";"""


MODELS_STATE = (
    "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"
    "nerWjHUFvKq3v5j9/v+zJ7bS"
)
