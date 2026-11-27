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
    raw = {k: row.get(k) for k in ("code", "status", "stage", "provider", "pay_method", "total_amount", "quantity", "test", "items",
                                   "shipping_fee", "refunded_amount")}
    raw.update(paid_at=row.get("paid_at"), cancelled_at=row.get("cancelled_at"), cancel_reason=row.get("cancel_reason"),
               shipping_memo=ship.get("memo"))
    # 배송비 별도 (2026-11-27) — 고객이 낸 배송비를 줄마다 상품 금액 비율로 나눠 total_price 에 더한다 (이익 계산이 맞게).
    #   부분 취소(cancelled_qty)는 남은 개수로, 다 취소된 줄은 취소 클레임으로.
    live = [max(0, int(it.get("qty") or 1) - int(it.get("cancelled_qty") or 0)) for it in items]
    amts = [int(it.get("unit_price") or 0) * n for it, n in zip(items, live)]
    fee = int(row.get("shipping_fee") or 0)
    base = sum(amts)
    shares = [fee * a // base if base else 0 for a in amts]
    if base and shares:
        k = max(range(len(amts)), key=lambda j: amts[j])
        shares[k] += fee - sum(shares)
    out = []
    for i, it in enumerate(items, 1):
        name = it.get("name") or ""
        gone = status != "CANCELLED" and live[i - 1] == 0
        st = "CANCELLED" if gone else status
        product, _, option = name.partition(" · ")
        sku = it.get("sku") or ""
        out.append({
            "market": "shop", "line_no": f"{row['code']}-{i}", "order_no": row["code"], "ship_unit_no": row["code"],
            "market_status": st, "confirmed": row["stage"] != "ordered",
            "stage": SHOP_STAGE.get(st, "received"),
            "ordered_at": row.get("created_at"), "paid_at": row.get("paid_at"), "ship_due_at": None,
            "product_name": product[:300], "option_name": option or None,
            "seller_code": sku.replace(":", "-") or None, "market_product_id": sku.split(":")[0] or None, "market_option_id": sku or None,
            "quantity": live[i - 1] or int(it.get("qty") or 1), "unit_price": it.get("unit_price"),
            "total_price": (amts[i - 1] + shares[i - 1]) if live[i - 1] else it.get("amount"),
            "receiver_name": ship.get("name") or "", "phone": ship.get("phone") or "", "zip": ship.get("zip") or "",
            "contact_phone": ship.get("phone") or "",
            "address": " ".join(x for x in (ship.get("addr1"), ship.get("addr2")) if x),
            "pccc": (pccc or "").upper(), "otp": None, "raw": raw,
            "claim_type": "CANCEL" if st == "CANCELLED" else None,
            "claim_status": "CANCEL_DONE" if st == "CANCELLED" else None,
            "claim_at": (row.get("cancelled_at") or row.get("updated_at")) if st == "CANCELLED" else None,
        })
    return out


_COLS = ("id, code, status, stage, items, total_amount, quantity, provider, pay_method, test, created_at, updated_at, paid_at, "
         "cancelled_at, cancel_reason, shipping_enc, pccc_enc, shipping_fee, refunded_amount")


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


# ── 자사몰 일부 취소 · 환불 (2026-11-27 사용자: "차액 돌려줘") ──
#   이 주문 줄에서 qty 개를 취소 → SHOP 이 상품 금액 + 배송비 차액(남은 상품으로 다시 계산)만큼 카드 부분 취소.
#   SHOP 내부 호출: POST {SHOP_INTERNAL_URL}/internal/orders/{code}/cancel-partial (X-Internal-Key). dry=True 면 계산만.
async def shop_refund(order_id: int, qty: int, dry: bool, reason: str | None = None) -> dict:
    import asyncio
    import urllib.error
    import urllib.request
    from fastapi import HTTPException
    from models.order.order import MarketOrder
    o = await MarketOrder.get_or_none(id=order_id)
    if not o or o.market != "shop" or not o.market_option_id or not o.order_no:
        raise HTTPException(status_code=404, detail="자사몰 주문 줄을 찾지 못했어요.")
    key, url = os.getenv("SHOP_INTERNAL_KEY"), os.getenv("SHOP_INTERNAL_URL", "http://shop_app:8000").rstrip("/")
    if not key:
        raise HTTPException(status_code=503, detail="SHOP 내부 호출 키가 없어요.")
    body = json.dumps({"items": [{"sku": o.market_option_id, "qty": int(qty)}],
                       "reason": (reason or "현지 품절 · 일부 취소")[:200]}).encode()
    req = urllib.request.Request(f"{url}/internal/orders/{o.order_no}/cancel-partial?dry={'true' if dry else 'false'}",
                                 data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-Internal-Key": key})

    def call():
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("detail")
            except Exception:
                msg = None
            raise HTTPException(status_code=e.code if e.code < 500 else 502, detail=msg or "자사몰 환불 실패") from None
    d = await asyncio.to_thread(call)
    d.pop("status", None)
    if not dry:   # 결과를 바로 주문 접수에 반영
        try:
            from datetime import timedelta, timezone
            from services.order.order_service import collect_market
            await collect_market("shop", None, trigger="shop_refund", since=datetime.now(timezone.utc) - timedelta(days=30))
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"자사몰 환불 뒤 다시 수집 실패: {type(e).__name__}")
    return d
