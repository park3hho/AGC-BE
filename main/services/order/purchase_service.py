"""타오바오 구매 · 중국 내 배송 (판매처 → 집운 창고).

추적: 추가·수정·연결 변경·삭제마다 연결된 마켓 주문마다 OrderEvent 한 줄 (data = 이전값 → 새값). 개인정보는 다루지 않는다.
상태가 '판매처 발송'·'창고 입고'로 바뀌었는데 시각이 비어 있으면 지금 시각을 넣는다."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from core.purchase_config import CN_STATUS, PURCHASE_TRACKED
from models.order.order import MarketOrder
from models.order.purchase import TaobaoPurchase, TaobaoPurchaseLink
from schemas.taobao_purchase import TaobaoPurchaseCreate, TaobaoPurchaseUpdate
from services.order.order_service import actor_of, log_event

FIELD_LABEL = {
    "taobao_order_no": "타오바오 주문번호", "shop_name": "판매처", "item_url": "상품 링크", "items": "옵션·수량",
    "paid_cny": "결제 위안", "purchased_at": "구매 일시", "purchased_by_id": "구매한 사람", "cn_status": "중국 배송 상태",
    "shipped_at": "판매처 발송", "cn_courier": "중국 택배사", "cn_tracking_no": "중국 운송장", "arrived_at": "창고 입고",
    "warehouse_ref": "집운 입고 번호", "status_source": "상태 출처", "memo": "메모",
}


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _plain(v):
    """기록·비교용 값 — Decimal 은 문자열 '12.30', 시각은 ISO."""
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()   # 보낸 +09:00 과 저장된 UTC 를 같은 값으로 비교
    return v


def alive():
    return TaobaoPurchase.filter(deleted_at=None)


def _order_brief(o: MarketOrder) -> dict:
    return {
        "id": o.id, "market": o.market, "order_no": o.order_no, "line_no": o.line_no,
        "product_name": o.product_name, "option_name": o.option_name, "quantity": o.quantity, "stage": o.stage,
    }


async def purchase_dict(p: TaobaoPurchase) -> dict:
    links = await TaobaoPurchaseLink.filter(purchase_id=p.id).prefetch_related("order").order_by("id")
    await p.fetch_related("purchased_by")
    return {
        "id": p.id,
        "taobao_order_no": p.taobao_order_no, "shop_name": p.shop_name, "item_url": p.item_url,
        "items": p.items or [], "paid_cny": _plain(p.paid_cny) if p.paid_cny is not None else None,
        "purchased_at": _iso(p.purchased_at),
        "purchased_by": {"id": p.purchased_by.id, "name": p.purchased_by.name} if p.purchased_by else None,
        "cn_status": p.cn_status, "shipped_at": _iso(p.shipped_at), "cn_courier": p.cn_courier,
        "cn_tracking_no": p.cn_tracking_no, "arrived_at": _iso(p.arrived_at), "warehouse_ref": p.warehouse_ref,
        "status_source": p.status_source, "status_checked_at": _iso(p.status_checked_at), "memo": p.memo,
        "orders": [{**_order_brief(l.order), "link_quantity": l.quantity} for l in links],
        "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat(),
    }


def _snapshot(p: TaobaoPurchase) -> dict:
    return {k: _plain(getattr(p, k)) for k in PURCHASE_TRACKED}


def _diff(before: dict, after: dict) -> dict:
    return {k: {"from": before[k], "to": after[k]} for k in PURCHASE_TRACKED if before[k] != after[k]}


def _label(p: TaobaoPurchase) -> str:
    return f"타오바오 {p.taobao_order_no}" if p.taobao_order_no else f"타오바오 구매 #{p.id}"


def _summary_of(changes: dict) -> str:
    names = [FIELD_LABEL.get(k, k) for k in changes]
    if "cn_status" in changes:
        to = changes["cn_status"]["to"]
        return f"중국 배송 → {CN_STATUS.get(to, to)}" + (f" (그 밖에 {', '.join(n for n in names if n != '중국 배송 상태')})" if len(names) > 1 else "")
    return f"{', '.join(names)} 수정"


async def _orders_exist(ids: list[int], conn) -> dict[int, MarketOrder]:
    rows = await MarketOrder.filter(id__in=ids).using_db(conn)
    found = {o.id: o for o in rows}
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"마켓 주문을 찾지 못했습니다: {missing}")
    return found


async def _check_order_no_free(no: str | None, self_id: int | None, conn) -> None:
    if not no:
        return
    qs = alive().filter(taobao_order_no=no).using_db(conn)
    if self_id is not None:
        qs = qs.exclude(id=self_id)
    if await qs.exists():
        raise HTTPException(status_code=409, detail=f"타오바오 주문번호 {no} 는 이미 등록돼 있습니다. 그 구매에 마켓 주문을 연결해주세요.")


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
    async def list(order_id: int | None, status: str | None, limit: int) -> list[dict]:
        qs = alive()
        if order_id:
            qs = qs.filter(links__order_id=order_id)
        if status:
            qs = qs.filter(cn_status=status)
        rows = await qs.distinct().order_by("-id").limit(limit)
        return [await purchase_dict(p) for p in rows]

    @staticmethod
    async def get(purchase_id: int) -> dict:
        p = await alive().get_or_none(id=purchase_id)
        if not p:
            raise HTTPException(status_code=404, detail="타오바오 구매를 찾지 못했습니다.")
        return await purchase_dict(p)

    @staticmethod
    async def create(body: TaobaoPurchaseCreate, auth: dict) -> dict:
        actor = actor_of(auth)
        data = body.model_dump(exclude={"orders", "items"})
        data["items"] = _items(body)
        _auto_times(data, None)
        async with in_transaction() as conn:
            orders = await _orders_exist([l.order_id for l in body.orders], conn)
            await _check_order_no_free(data.get("taobao_order_no"), None, conn)
            p = await TaobaoPurchase.create(
                **data, purchased_by_id=auth["user_id"], created_by_id=auth["user_id"], using_db=conn,
            )
            for l in body.orders:
                await TaobaoPurchaseLink.create(purchase_id=p.id, order_id=l.order_id, quantity=l.quantity, using_db=conn)
        snap = _snapshot(p)
        for l in body.orders:
            await log_event(
                orders[l.order_id], actor, "purchase_created", f"{_label(p)} 추가 — {CN_STATUS[p.cn_status]}",
                {"purchase_id": p.id, "values": {k: v for k, v in snap.items() if v not in (None, [], "")},
                 "link_quantity": l.quantity, "linked_orders": [x.order_id for x in body.orders]},
            )
        return await purchase_dict(p)

    @staticmethod
    async def update(purchase_id: int, body: TaobaoPurchaseUpdate, auth: dict) -> dict:
        actor = actor_of(auth)
        sent = body.model_fields_set
        data = body.model_dump(exclude_unset=True, exclude={"orders", "items"})
        if "items" in sent:
            data["items"] = _items(body)
        if not data and "orders" not in sent:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        async with in_transaction() as conn:
            p = await alive().using_db(conn).select_for_update().get_or_none(id=purchase_id)
            if not p:
                raise HTTPException(status_code=404, detail="타오바오 구매를 찾지 못했습니다.")
            if "taobao_order_no" in data:
                await _check_order_no_free(data["taobao_order_no"], p.id, conn)
            _auto_times(data, p)
            before = _snapshot(p)
            old_links = {l.order_id: l for l in await TaobaoPurchaseLink.filter(purchase_id=p.id).using_db(conn)}
            if data:
                data["status_source"] = "manual"
                await p.update_from_dict(data).save(using_db=conn)
            changes = _diff(before, _snapshot(p))

            added, removed, qty_changed = [], [], []
            if body.orders is not None:
                new = {l.order_id: l.quantity for l in body.orders}
                await _orders_exist(list(new), conn)
                for oid, q in new.items():
                    if oid not in old_links:
                        await TaobaoPurchaseLink.create(purchase_id=p.id, order_id=oid, quantity=q, using_db=conn)
                        added.append(oid)
                    elif old_links[oid].quantity != q:
                        qty_changed.append({"order_id": oid, "from": old_links[oid].quantity, "to": q})
                        old_links[oid].quantity = q
                        await old_links[oid].save(using_db=conn)
                removed = [oid for oid in old_links if oid not in new]
                if removed:
                    await TaobaoPurchaseLink.filter(purchase_id=p.id, order_id__in=removed).using_db(conn).delete()
            if not changes and not added and not removed and not qty_changed:
                return await purchase_dict(p)
            await p.save(update_fields=["updated_at"], using_db=conn)

        now_ids = [l.order_id for l in await TaobaoPurchaseLink.filter(purchase_id=p.id)]
        orders = {o.id: o for o in await MarketOrder.filter(id__in=set(now_ids) | set(removed))}
        for oid in now_ids:
            if oid in added:
                await log_event(orders[oid], actor, "purchase_linked", f"{_label(p)} 연결",
                                {"purchase_id": p.id, "linked_orders": now_ids})
            elif changes or qty_changed:
                await log_event(orders[oid], actor, "purchase_changed", f"{_label(p)} — {_summary_of(changes) if changes else '연결 수량 수정'}",
                                {"purchase_id": p.id, "changes": changes, "link_quantity": qty_changed})
        for oid in removed:
            await log_event(orders[oid], actor, "purchase_unlinked", f"{_label(p)} 연결 해제",
                            {"purchase_id": p.id, "linked_orders": now_ids})
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
        for l in await TaobaoPurchaseLink.filter(purchase_id=p.id).prefetch_related("order"):
            await log_event(l.order, actor, "purchase_deleted", f"{_label(p)} 삭제",
                            {"purchase_id": p.id, "values": {k: v for k, v in snap.items() if v not in (None, [], "")}})
