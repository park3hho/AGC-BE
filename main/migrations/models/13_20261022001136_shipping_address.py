from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "shipping_address" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "created_at" TIMESTAMPTZ NOT NULL,
    "updated_at" TIMESTAMPTZ NOT NULL,
    "name" VARCHAR(100) NOT NULL,
    "country" VARCHAR(2) NOT NULL,
    "zip_code" VARCHAR(20),
    "address" VARCHAR(300) NOT NULL,
    "address_detail" VARCHAR(300),
    "phone" VARCHAR(40),
    "uses" JSONB NOT NULL,
    "defaults" JSONB NOT NULL,
    "market_codes" JSONB NOT NULL,
    "memo" TEXT,
    "deleted_at" TIMESTAMPTZ,
    "created_by_id" INT REFERENCES "app_user" ("id") ON DELETE SET NULL
);
COMMENT ON TABLE "shipping_address" IS '출고지·반품지 주소록 — 실제 장소 1곳 = 1행. 마켓(네이버·쿠팡)마다 따로 받은 주소 코드를 market_codes 에 묶어 둔다.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "shipping_address";"""


MODELS_STATE = (
    "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"
    "dJiGxf3dnNFm9tik1up7DNxeznfwCtG9GQ"
)
