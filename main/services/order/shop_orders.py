"""자사몰(eidofood.com) 주문 → AGC 주문 접수 (2026-10-29).

자사몰 주문은 같은 DB 의 shop 스키마(shop.shop_order)에 있다. 마켓 API 대신 그 표를 읽어 마켓 주문과 같은 줄로 만든다.
- 결제된 주문만 (paid_at 있음). 시험 결제(test=true)는 SHOP_ORDER_INCLUDE_TEST=1 일 때만.
- 주문 1건의 상품 여러 개 = AGC 주문 줄 여러 개 (line_no = 주문번호-순번). 발주확인 · 배송 완료는 주문 단위(ship_unit_no = 주문번호).
- 개인정보(배송지 · 통관부호)는 자사몰 키(SHOP_DATA_SECRET_KEY)로 풀어서 AGC 키로 다시 암호화해 저장한다.

자사몰 쪽 단계(shop_order.stage)가 원본이다: ordered(결제 완료) → preparing(주문 확인 — 고객 즉시 취소 막힘) → delivered(배송 완료).
AGC 발주확인 · 배송 완료 버튼이 이 칸을 바꾸고, 수집이 다시 읽어 market_status 로 만든다.
그 사이 단계(해외 물류센터 · 국제 배송 · 통관 · 국내 배송)는 자사몰이 AGC 구매기록 · 집운 기록을 읽어 고객에게 보여 준다 (SHOP-BE services/tracking.py)."""

import json
import os
from datetime import datetime

from cryptography.fernet import Fernet
from tortoise import Tortoise

SHOP_STATUS = {"PAID": "결제 완료", "CONFIRMED": "주문 확인", "DELIVERED": "배송 완료", "CANCELLED": "취소"}
SHOP_STAGE = {"CANCELLED": "cancelled", "DELIVERED": "done"}       # 그 외 = 접수 (타오바오 구매가 있으면 처리)

_KEY = os.getenv("SHOP_DATA_SECRET_KEY", "")
_F = Fernet(_KEY.encode()) if _KEY else None
INCLUDE_TEST = os.getenv("SHOP_ORDER_INCLUDE_TEST", "") == "1"


def _dec(v: str | None):
    if not v or _F is None:
        return None
    return json.loads(_F.decrypt(v.encode()).decode())


def _conn():
    return Tortoise.get_connection("default")


def shop_market_status(status: str, stage: str) -> str:
    if status == "cancelled":
        return "CANCELLED"
    if stage == "delivered":
        return "DELIVERED"
    if stage != "ordered":
        return "CONFIRMED"
    return "PAID"


def parse_shop(row: dict) -> list[dict]:
    if _F is None:
        raise RuntimeError("SHOP_DATA_SECRET_KEY 가 없어 자사몰 주문 배송지를 읽을 수 없습니다.")
    ship = _dec(row.get("shipping_enc")) or {}
    pccc = _dec(row.get("pccc_enc")) or ""
    status = shop_market_status(row["status"], row["stage"])
    items = row["items"] if isinstance(row["items"], list) else json.loads(row["items"] or "[]")
    raw = {k: row.get(k) for k in ("code", "status", "stage", "provider", "pay_method", "total_amount", "quantity", "test", "items")}
    raw.update(paid_at=row.get("paid_at"), cancelled_at=row.get("cancelled_at"), cancel_reason=row.get("cancel_reason"),
               shipping_memo=ship.get("memo"))
    out = []
    for i, it in enumerate(items, 1):
        name = it.get("name") or ""
        product, _, option = name.partition(" · ")
        sku = it.get("sku") or ""
        out.append({
            "market": "shop", "line_no": f"{row['code']}-{i}", "order_no": row["code"], "ship_unit_no": row["code"],
            "market_status": status, "confirmed": row["stage"] != "ordered",
            "stage": SHOP_STAGE.get(status, "received"),
            "ordered_at": row.get("created_at"), "paid_at": row.get("paid_at"), "ship_due_at": None,
            "product_name": product[:300], "option_name": option or None,
            "seller_code": sku.replace(":", "-") or None, "market_product_id": sku.split(":")[0] or None, "market_option_id": sku or None,
            "quantity": int(it.get("qty") or 1), "unit_price": it.get("unit_price"), "total_price": it.get("amount"),
            "receiver_name": ship.get("name") or "", "phone": ship.get("phone") or "", "zip": ship.get("zip") or "",
            "contact_phone": ship.get("phone") or "",
            "address": " ".join(x for x in (ship.get("addr1"), ship.get("addr2")) if x),
            "pccc": (pccc or "").upper(), "otp": None, "raw": raw,
            "claim_type": "CANCEL" if status == "CANCELLED" else None,
            "claim_status": "CANCEL_DONE" if status == "CANCELLED" else None,
            "claim_at": row.get("cancelled_at") if status == "CANCELLED" else None,
        })
    return out


_COLS = "id, code, status, stage, items, total_amount, quantity, provider, pay_method, test, created_at, paid_at, cancelled_at, cancel_reason, shipping_enc, pccc_enc"


async def shop_orders_since(start: datetime, end: datetime) -> list[dict]:
    q = f"select {_COLS} from shop.shop_order where paid_at is not null and updated_at >= $1 and updated_at <= $2"
    if not INCLUDE_TEST:
        q += " and test = false"
    return await _conn().execute_query_dict(q + " order by id", [start, end])


async def shop_order(code: str) -> dict | None:
    rows = await _conn().execute_query_dict(f"select {_COLS} from shop.shop_order where code = $1", [code])
    return rows[0] if rows else None


async def set_shop_stage(code: str, frm: str, to: str) -> bool:
    """자사몰 주문 단계를 바꾼다 — 결제된 주문이고 지금 단계가 frm 일 때만 (고객 취소와 동시에 눌려도 한쪽만 된다)."""
    rows = await _conn().execute_query_dict(
        "update shop.shop_order set stage = $3, updated_at = now() where code = $1 and status = 'paid' and stage = $2 returning id",
        [code, frm, to])
    return bool(rows)
