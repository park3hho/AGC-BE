"""타오바오 구매 · 중국 내 배송 (판매처 → 집운 창고). 고객 주문(MarketOrder) 1건에 붙는다.

추적: 추가·수정·삭제마다 그 고객 주문의 OrderEvent 한 줄 (data.changes = 이전값 → 새값). 개인정보는 다루지 않는다.
상태가 '판매처 발송'·'창고 입고'로 바뀌었는데 시각이 비어 있으면 지금 시각을 넣는다."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from core.purchase_config import CN_STATUS, PURCHASE_TRACKED
from models.order.order import MarketOrder
from models.order.purchase import TaobaoPurchase
from schemas.taobao_purchase import TaobaoPurchaseCreate, TaobaoPurchaseUpdate
from services.order.order_service import actor_of, log_event

FIELD_LABEL = {
    "taobao_order_no": "타오바오 주문번호", "shop_name": "판매처", "item_url": "상품 링크", "items": "옵션·수량",
    "paid_cny": "결제 위안", "purchased_at": "구매 일시", "purchased_by_id": "구매한 사람", "cn_status": "중국 배송 상태",
    "shipped_at": "판매처 발송", "cn_courier": "중국 택배사", "cn_tracking_no": "중국 운송장", "arrived_at": "창고 입고",
    "status_source": "상태 출처", "memo": "메모",
}


def _plain(v):
    """기록·비교용 값 — Decimal 은 '12.30', 시각은 UTC ISO (보낸 +09:00 과 저장된 UTC 를 같은 값으로 비교)."""
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    return v


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def alive():
    return TaobaoPurchase.filter(deleted_at=None)


async def purchase_dict(p: TaobaoPurchase) -> dict:
    await p.fetch_related("purchased_by", "order")
    o = p.order
    return {
        "id": p.id,
        "order": {"id": o.id, "code": o.code, "market": o.market, "order_no": o.order_no, "line_no": o.line_no,
                  "product_name": o.product_name, "option_name": o.option_name, "quantity": o.quantity},
        "taobao_order_no": p.taobao_order_no, "shop_name": p.shop_name, "item_url": p.item_url,
        "items": p.items or [], "paid_cny": _plain(p.paid_cny) if p.paid_cny is not None else None,
        "purchased_at": _iso(p.purchased_at),
        "purchased_by": {"id": p.purchased_by.id, "name": p.purchased_by.name} if p.purchased_by else None,
        "cn_status": p.cn_status, "shipped_at": _iso(p.shipped_at), "cn_courier": p.cn_courier,
        "cn_tracking_no": p.cn_tracking_no, "arrived_at": _iso(p.arrived_at),
        "status_source": p.status_source, "status_checked_at": _iso(p.status_checked_at), "memo": p.memo,
        "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(),
    }


def _snapshot(p: TaobaoPurchase) -> dict:
    return {k: _plain(getattr(p, k)) for k in PURCHASE_TRACKED}


def _summary_of(changes: dict) -> str:
    names = [FIELD_LABEL.get(k, k) for k in changes]
    if "cn_status" in changes:
        to = changes["cn_status"]["to"]
        rest = [n for n in names if n != "중국 배송 상태"]
        return f"중국 배송 → {CN_STATUS.get(to, to)}" + (f" (그 밖에 {', '.join(rest)})" if rest else "")
    return f"{', '.join(names)} 수정"


async def _check_no_free(no: str, self_id: int | None, conn) -> None:
    qs = alive().filter(taobao_order_no=no).using_db(conn)
    if self_id is not None:
        qs = qs.exclude(id=self_id)
    other = await qs.prefetch_related("order").first()
    if other:
        raise HTTPException(
            status_code=409,
            detail=f"타오바오 주문번호 {no} 는 이미 {other.order.code or '다른 고객 주문'} 에 등록돼 있습니다.",
        )


def _auto_times(data: dict, p: TaobaoPurchase | None) -> None:
    """상태가 발송·입고로 바뀌었는데 시각이 없으면 지금."""
    now = datetime.now(timezone.utc)
    status = data.get("cn_status", p.cn_status if p else "ordered")
    if status in ("shipped", "arrived") and not data.get("shipped_at") and not (p and p.shipped_at):
        data["shipped_at"] = now
    if status == "arrived" and not data.get("arrived_at") and not (p and p.arrived_at):
        data["arrived_at"] = now


def _items(body) -> list[dict]:
    return [{"name": i.name, "qty": i.qty, "price_cny": f"{i.price_cny:.2f}" if i.price_cny is not None else None}
            for i in body.items]


class TaobaoPurchaseService:
    @staticmethod
    async def list(order_id: int | None, status: str | None, q: str | None, limit: int) -> list[dict]:
        qs = alive()
        if order_id:
            qs = qs.filter(order_id=order_id)
        if status:
            qs = qs.filter(cn_status=status)
        if q:
            qs = qs.filter(taobao_order_no__icontains=q.replace(" ", ""))
        return [await purchase_dict(p) for p in await qs.order_by("-id").limit(limit)]

    @staticmethod
    async def get(purchase_id: int) -> dict:
        p = await alive().get_or_none(id=purchase_id)
        if not p:
            raise HTTPException(status_code=404, detail="타오바오 구매를 찾지 못했습니다.")
        return await purchase_dict(p)

    @staticmethod
    async def create(body: TaobaoPurchaseCreate, auth: dict) -> dict:
        actor = actor_of(auth)
        data = body.model_dump(exclude={"order_id", "items"})
        data["items"] = _items(body)
        _auto_times(data, None)
        async with in_transaction() as conn:
            order = await MarketOrder.get_or_none(id=body.order_id).using_db(conn)
            if not order:
                raise HTTPException(status_code=404, detail="고객 주문을 찾지 못했습니다.")
            # 발주확인 전에는 타오바오 구매를 등록하지 않는다 — 결제완료 상태에선 고객 취소가 바로 돼서 산 뒤 손해 (2026-10-25)
            if order.stage == "cancelled":
                raise HTTPException(status_code=409, detail="취소된 주문에는 타오바오 구매를 등록할 수 없습니다.")
            if not order.confirmed:
                raise HTTPException(status_code=409, detail="먼저 마켓에 발주확인을 보내 주세요 (주문이 상품준비중이 된 뒤에 타오바오 구매를 등록해요).")
            await _check_no_free(data["taobao_order_no"], None, conn)
            p = await TaobaoPurchase.create(
                order_id=order.id, **data, purchased_by_id=auth["user_id"], created_by_id=auth["user_id"],
                using_db=conn,
            )
        snap = _snapshot(p)
        await log_event(
            order, actor, "purchase_created", f"타오바오 {p.taobao_order_no} 등록 — {CN_STATUS[p.cn_status]}",
            {"purchase_id": p.id, "values": {k: v for k, v in snap.items() if v not in (None, [], "")}},
        )
        return await purchase_dict(p)

    @staticmethod
    async def update(purchase_id: int, body: TaobaoPurchaseUpdate, auth: dict) -> dict:
        actor = actor_of(auth)
        data = body.model_dump(exclude_unset=True, exclude={"items"})
        if "items" in body.model_fields_set:
            data["items"] = _items(body)
        if not data:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        async with in_transaction() as conn:
            p = await alive().using_db(conn).select_for_update().get_or_none(id=purchase_id)
            if not p:
                raise HTTPException(status_code=404, detail="타오바오 구매를 찾지 못했습니다.")
            if "taobao_order_no" in data:
                await _check_no_free(data["taobao_order_no"], p.id, conn)
            _auto_times(data, p)
            before = _snapshot(p)
            data["status_source"] = "manual"
            await p.update_from_dict(data).save(using_db=conn)
            after = _snapshot(p)
        changes = {k: {"from": before[k], "to": after[k]} for k in PURCHASE_TRACKED if before[k] != after[k]}
        if changes:
            order = await MarketOrder.get(id=p.order_id)
            await log_event(
                order, actor, "purchase_changed", f"타오바오 {p.taobao_order_no} — {_summary_of(changes)}",
                {"purchase_id": p.id, "changes": changes},
            )
        return await purchase_dict(p)

    @staticmethod
    async def delete(purchase_id: int, auth: dict) -> None:
        actor = actor_of(auth)
        p = await alive().get_or_none(id=purchase_id)
        if not p:
            raise HTTPException(status_code=404, detail="타오바오 구매를 찾지 못했습니다.")
        p.deleted_at = datetime.now(timezone.utc)
        await p.save(update_fields=["deleted_at", "updated_at"])
        snap = _snapshot(p)
        await log_event(
            await MarketOrder.get(id=p.order_id), actor, "purchase_deleted", f"타오바오 {p.taobao_order_no} 삭제",
            {"purchase_id": p.id, "values": {k: v for k, v in snap.items() if v not in (None, [], "")}},
        )
