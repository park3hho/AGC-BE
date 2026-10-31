"""집운 기록 — 배대지(집운) 배송 요청 · 배송비 결제 · 출고 · 국제 운송장 · 국내 송장. 고객 주문(MarketOrder) 1건에 붙는다.

추적: 추가·수정·삭제마다 그 고객 주문의 OrderEvent 한 줄 (jiyun_created · jiyun_changed · jiyun_deleted).
data 에 단계(국제 발송) · 관련 번호(집운 번호 · H B/L · 국내 송장) · 이전값 → 새값. 개인정보는 다루지 않는다.
상태를 '출고'로 바꿨는데 출고 시각이 비어 있으면 지금 시각을 넣는다."""

import logging
from services.finance import fin_expense
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from core.jiyun_config import JIYUN_FIELD_LABEL, JIYUN_STATUS, JIYUN_TRACKED
from core.shipping_config import COURIERS
from models.order.jiyun import JiyunShipment
from models.order.order import MarketOrder
from schemas.jiyun import JiyunCreate, JiyunUpdate
from services.order.order_service import actor_of, log_event

logger = logging.getLogger(__name__)


def alive():
    return JiyunShipment.filter(deleted_at=None)


def _plain(v):
    """기록·비교용 값 — Decimal 은 '12.30', 시각은 UTC ISO."""
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    return v


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


async def jiyun_dict(j: JiyunShipment) -> dict:
    await j.fetch_related("order")
    o = j.order
    return {
        "id": j.id,
        "order": {"id": o.id, "code": o.code, "market": o.market, "order_no": o.order_no, "line_no": o.line_no,
                  "product_name": o.product_name, "option_name": o.option_name, "quantity": o.quantity},
        "jiyun_no": j.jiyun_no, "status": j.status, "packages": j.packages or [],
        "weight_kg": _plain(j.weight_kg) if j.weight_kg is not None else None,
        "fee_cny": _plain(j.fee_cny) if j.fee_cny is not None else None,
        "transport": j.transport, "requested_at": _iso(j.requested_at),
        "pay_method": j.pay_method, "pay_currency": j.pay_currency,
        "pay_amount": _plain(j.pay_amount) if j.pay_amount is not None else None,
        "charged_krw": j.charged_krw, "charged_status": j.charged_status, "charged_at": _iso(j.charged_at),
        "charged_source": j.charged_source,
        "dispatched_at": _iso(j.dispatched_at), "hbl": j.hbl, "kr_courier": j.kr_courier,
        "kr_courier_name": COURIERS.get(j.kr_courier, {}).get("name") if j.kr_courier else None,
        "kr_tracking_no": j.kr_tracking_no, "memo": j.memo,
        "created_at": j.created_at.isoformat(), "updated_at": j.updated_at.isoformat(),
    }


def _snapshot(j: JiyunShipment) -> dict:
    return {k: _plain(getattr(j, k)) for k in JIYUN_TRACKED}


def _refs(j: JiyunShipment) -> dict:
    r = {"jiyun_request_no": j.jiyun_no, "hbl": j.hbl,
         "kr_courier": COURIERS.get(j.kr_courier, {}).get("name") if j.kr_courier else None,
         "kr_tracking_no": j.kr_tracking_no}
    return {k: v for k, v in r.items() if v}


def _summary_of(changes: dict) -> str:
    names = [JIYUN_FIELD_LABEL.get(k, k) for k in changes]
    if "status" in changes:
        to = changes["status"]["to"]
        rest = [n for n in names if n != "상태"]
        return f"→ {JIYUN_STATUS.get(to, to)}" + (f" (그 밖에 {', '.join(rest)})" if rest else "")
    return f"{', '.join(names)} 수정"


async def _check_no_free(no: str, self_id: int | None, conn) -> None:
    qs = alive().filter(jiyun_no=no).using_db(conn)
    if self_id is not None:
        qs = qs.exclude(id=self_id)
    other = await qs.prefetch_related("order").first()
    if other:
        raise HTTPException(status_code=409, detail=f"집운 번호 {no} 는 이미 {other.order.code or '다른 고객 주문'} 에 등록돼 있습니다.")


def _auto_times(data: dict, j: JiyunShipment | None) -> None:
    if data.get("status", j.status if j else "requested") == "dispatched" and not data.get("dispatched_at") and not (j and j.dispatched_at):
        data["dispatched_at"] = datetime.now(timezone.utc)


def _occurred(data: dict, j: JiyunShipment) -> str | None:
    """이 기록이 실제로 일어난 때 — 출고로 바뀌었으면 출고 시각, 처음이면 배송 요청 시각."""
    t = j.dispatched_at if data.get("status") == "dispatched" else j.requested_at
    return _iso(t) if t else None


class JiyunService:
    @staticmethod
    async def list(order_id: int | None, status: str | None, q: str | None, limit: int) -> list[dict]:
        qs = alive()
        if order_id:
            qs = qs.filter(order_id=order_id)
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(jiyun_no__icontains=q.replace(" ", ""))
        return [await jiyun_dict(j) for j in await qs.order_by("-id").limit(limit)]

    @staticmethod
    async def get(jiyun_id: int) -> dict:
        j = await alive().get_or_none(id=jiyun_id)
        if not j:
            raise HTTPException(status_code=404, detail="집운 기록을 찾지 못했습니다.")
        return await jiyun_dict(j)

    @staticmethod
    async def create(body: JiyunCreate, auth: dict) -> dict:
        actor = actor_of(auth)
        data = body.model_dump(exclude={"order_id"})
        data["packages"] = data.get("packages") or []
        if data.get("charged_status") is None:
            data.pop("charged_status", None)
        _auto_times(data, None)
        async with in_transaction() as conn:
            order = await MarketOrder.get_or_none(id=body.order_id).using_db(conn)
            if not order:
                raise HTTPException(status_code=404, detail="고객 주문을 찾지 못했습니다.")
            if order.stage == "cancelled":
                raise HTTPException(status_code=409, detail="취소된 주문에는 집운 기록을 등록할 수 없습니다.")
            await _check_no_free(data["jiyun_no"], None, conn)
            j = await JiyunShipment.create(order_id=order.id, **data, created_by_id=auth.get("user_id"), using_db=conn)
        snap = _snapshot(j)
        await log_event(
            order, actor, "jiyun_created", f"집운 {j.jiyun_no} 등록 — {JIYUN_STATUS[j.status]}",
            {"jiyun_id": j.id, "step": "국제 발송", "stage": "process", "source": "jiyun",
             "occurred_at": _occurred({}, j), "refs": _refs(j),
             "values": {k: v for k, v in snap.items() if v not in (None, [], "")}},
        )
        fin_expense.kick()   # FIN 지출 원장으로 (2026-10-30)
        return await jiyun_dict(j)

    @staticmethod
    async def update(jiyun_id: int, body: JiyunUpdate, auth: dict) -> dict:
        actor = actor_of(auth)
        data = body.model_dump(exclude_unset=True)
        if "packages" in data and data["packages"] is None:
            data["packages"] = []
        if not data:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        async with in_transaction() as conn:
            j = await alive().using_db(conn).select_for_update().get_or_none(id=jiyun_id)
            if not j:
                raise HTTPException(status_code=404, detail="집운 기록을 찾지 못했습니다.")
            if "jiyun_no" in data:
                await _check_no_free(data["jiyun_no"], j.id, conn)
            _auto_times(data, j)
            before = _snapshot(j)
            await j.update_from_dict(data).save(using_db=conn)
            after = _snapshot(j)
        changes = {k: {"from": before[k], "to": after[k]} for k in JIYUN_TRACKED if before[k] != after[k]}
        if changes:
            order = await MarketOrder.get(id=j.order_id)
            await log_event(
                order, actor, "jiyun_changed", f"집운 {j.jiyun_no} — {_summary_of(changes)}",
                {"jiyun_id": j.id, "step": "국제 발송", "stage": "process", "source": "jiyun",
                 "occurred_at": _occurred(data, j) if "status" in changes else None,
                 "refs": _refs(j), "changes": changes},
            )
        fin_expense.kick()   # FIN 지출 원장으로 (2026-10-30)
        return await jiyun_dict(j)

    @staticmethod
    async def delete(jiyun_id: int, auth: dict) -> None:
        actor = actor_of(auth)
        j = await alive().get_or_none(id=jiyun_id)
        if not j:
            raise HTTPException(status_code=404, detail="집운 기록을 찾지 못했습니다.")
        j.deleted_at = datetime.now(timezone.utc)
        await j.save(update_fields=["deleted_at", "updated_at"])
        fin_expense.kick()
        order = await MarketOrder.get(id=j.order_id)
        await log_event(order, actor, "jiyun_deleted", f"집운 {j.jiyun_no} 기록 삭제",
                        {"jiyun_id": j.id, "values": _snapshot(j)})
