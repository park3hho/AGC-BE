"""집운 가용재고 (2026-11-18) — models/order/stock.py

- 등록: 취소된 주문의 타오바오 구매(판매처가 이미 보내서 즉시 환불이 안 된 것)를 재고로 올린다.
- 맞는 재고: 새 주문의 판매자 상품코드(SKU)와 같은 available 재고 — 점검 루틴이 타오바오에서 사기 전에 먼저 본다.
- 쓰기: 재고 소포의 타오바오 구매를 새 주문으로 옮긴다 (원가가 새 주문에 붙음). 두 주문에 OrderEvent 를 남긴다.
- 닫기: returned(판매처 반품·환불) · written_off(버림·손실).
추적: 등록·쓰기·닫기마다 관련 주문의 OrderEvent 한 줄. 개인정보는 다루지 않는다.
"""
import re
from datetime import date, datetime, timezone

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from core.purchase_config import CN_STATUS
from models.order.order import MarketOrder
from models.order.purchase import TaobaoPurchase
from models.order.stock import JiyunStock
from services.order.order_service import actor_of, log_event, restage

SKU_RE = re.compile(r"^(PR-\d{6}-[0-9A-Fa-f]{4})(?:-(\d+)(?:[xX](\d+))?)?$")
STATUS = {"available": "보관 중", "used": "씀", "returned": "반품", "written_off": "손실 처리"}
CLOSE_TO = ("returned", "written_off", "available")


def alive():
    return JiyunStock.filter(deleted_at=None)


def parse_sku(code: str | None) -> tuple[str | None, int | None, int]:
    m = SKU_RE.match((code or "").strip())
    if not m:
        return None, None, 1
    return m.group(1).upper(), int(m.group(2)) if m.group(2) else None, int(m.group(3)) if m.group(3) else 1


def _iso(v):
    return v.isoformat() if v else None


async def stock_dict(s: JiyunStock) -> dict:
    p = await TaobaoPurchase.get_or_none(id=s.purchase_id)
    src = await MarketOrder.get_or_none(id=s.source_order_id) if s.source_order_id else None
    used = await MarketOrder.get_or_none(id=s.used_order_id) if s.used_order_id else None
    where = None
    if p:
        where = "창고" if p.cn_status == "arrived" else ("이동 중" if p.cn_status == "shipped" else CN_STATUS.get(p.cn_status, p.cn_status))
    return {
        "id": s.id, "status": s.status, "status_label": STATUS.get(s.status, s.status),
        "sku": s.sku, "product_code": s.product_code, "option_id": s.option_id, "bundle_qty": s.bundle_qty, "label": s.label,
        "cost_cny": float(s.cost_cny) if s.cost_cny is not None else None, "cost_krw": s.cost_krw,
        "expires_on": _iso(s.expires_on), "used_at": _iso(s.used_at), "closed_at": _iso(s.closed_at),
        "created_at": _iso(s.created_at), "memo": s.memo,
        "purchase": {
            "id": p.id, "taobao_order_no": p.taobao_order_no, "shop_name": p.shop_name, "cn_status": p.cn_status,
            "cn_tracking_no": p.cn_tracking_no, "arrived_at": _iso(p.arrived_at), "order_id": p.order_id,
        } if p else None,
        "where": where,
        "source_order": {"id": src.id, "code": src.code, "market": src.market} if src else None,
        "used_order": {"id": used.id, "code": used.code, "market": used.market} if used else None,
    }


async def held_purchase_ids() -> set[int]:
    """보관 중(available) 재고의 구매 id — 매출 현황에서 취소 주문 손실로 세지 않는다."""
    return set(await alive().filter(status="available").values_list("purchase_id", flat=True))


class StockService:
    @staticmethod
    async def list(status: str | None, sku: str | None) -> list[dict]:
        qs = alive()
        if status and status != "all":
            qs = qs.filter(status=status)
        if sku:
            qs = qs.filter(sku=sku.strip())
        return [await stock_dict(s) for s in await qs.order_by("status", "-created_at")]

    @staticmethod
    async def match(order_id: int) -> list[dict]:
        """이 주문에 쓸 수 있는 재고 — SKU(상품코드·옵션·묶음 수)가 같은 available."""
        o = await MarketOrder.get_or_none(id=order_id)
        if not o:
            raise HTTPException(status_code=404, detail="고객 주문을 찾지 못했습니다.")
        code, opt, qty = parse_sku(o.seller_code)
        if not code:
            return []
        qs = alive().filter(status="available", product_code=code, bundle_qty=qty * (o.quantity or 1))
        if opt is not None:
            qs = qs.filter(option_id=opt)
        return [await stock_dict(s) for s in await qs.order_by("created_at")]

    @staticmethod
    async def create(purchase_id: int, label: str | None, expires_on: date | None, memo: str | None, auth: dict) -> dict:
        actor = actor_of(auth)
        p = await TaobaoPurchase.get_or_none(id=purchase_id, deleted_at=None)
        if not p:
            raise HTTPException(status_code=404, detail="타오바오 구매를 찾지 못했습니다.")
        if p.cn_status == "cancelled" or "退款成功" in (p.memo or ""):
            raise HTTPException(status_code=409, detail="이미 환불된 구매는 재고로 올릴 수 없습니다.")
        if await alive().filter(purchase_id=p.id).exclude(status__in=["returned", "written_off"]).exists():
            raise HTTPException(status_code=409, detail="이 구매는 이미 재고로 올라가 있습니다.")
        o = await MarketOrder.get(id=p.order_id)
        if o.stage != "cancelled":
            raise HTTPException(status_code=409, detail="취소된 주문의 구매만 재고로 올릴 수 있습니다 (지금 주문이 살아 있어요).")
        code, opt, qty = parse_sku(o.seller_code)
        name = label or " · ".join(x for x in [o.product_name, o.option_name] if x)
        s = await JiyunStock.create(
            purchase_id=p.id, source_order_id=o.id, sku=(o.seller_code or "").strip() or None, product_code=code,
            option_id=opt, bundle_qty=qty * (o.quantity or 1), label=name[:200], status="available",
            cost_cny=p.paid_cny, cost_krw=p.charged_krw, expires_on=expires_on, memo=memo,
            created_by_id=(auth or {}).get("user_id"),
        )
        await log_event(o, actor, "stock_created", f"집운 재고 #{s.id} 로 보관 — 타오바오 {p.taobao_order_no} ({name[:60]})",
                        {"stock_id": s.id, "purchase_id": p.id, "sku": s.sku})
        return await stock_dict(s)

    @staticmethod
    async def use(stock_id: int, order_id: int | None, auth: dict, order_code: str | None = None) -> dict:
        actor = actor_of(auth)
        if not order_id and order_code:
            found = await MarketOrder.get_or_none(code=order_code.strip().upper())
            order_id = found.id if found else None
        if not order_id:
            raise HTTPException(status_code=404, detail="고객 주문을 찾지 못했습니다 (주문 코드 확인).")
        async with in_transaction() as conn:
            s = await alive().using_db(conn).select_for_update().get_or_none(id=stock_id)
            if not s:
                raise HTTPException(status_code=404, detail="재고를 찾지 못했습니다.")
            if s.status != "available":
                raise HTTPException(status_code=409, detail=f"이 재고는 지금 '{STATUS.get(s.status, s.status)}' 상태라 쓸 수 없습니다.")
            o = await MarketOrder.using_db(conn).get_or_none(id=order_id)
            if not o:
                raise HTTPException(status_code=404, detail="고객 주문을 찾지 못했습니다.")
            if o.stage == "cancelled":
                raise HTTPException(status_code=409, detail="취소된 주문에는 재고를 쓸 수 없습니다.")
            if await TaobaoPurchase.using_db(conn).filter(order_id=o.id, deleted_at=None).exclude(cn_status="cancelled").exists():
                raise HTTPException(status_code=409, detail="이 주문에는 이미 타오바오 구매가 있습니다. 재고를 쓰려면 그 구매를 먼저 정리해 주세요.")
            code, opt, qty = parse_sku(o.seller_code)
            if s.product_code and code and (s.product_code != code or (s.option_id is not None and opt is not None and s.option_id != opt)):
                raise HTTPException(status_code=409, detail=f"상품이 다릅니다 — 재고 {s.sku} / 주문 {o.seller_code}.")
            p = await TaobaoPurchase.using_db(conn).select_for_update().get(id=s.purchase_id)
            old_order_id = p.order_id
            p.order_id = o.id
            p.memo = (p.memo or "") + f" [집운 재고 #{s.id} → {o.code} 에 씀 {datetime.now(timezone.utc):%Y-%m-%d}]"
            await p.save(using_db=conn, update_fields=["order_id", "memo", "updated_at"])
            now = datetime.now(timezone.utc)
            s.status, s.used_order_id, s.used_at, s.closed_at = "used", o.id, now, now
            await s.save(using_db=conn)
        old = await MarketOrder.get_or_none(id=old_order_id)
        summary = f"집운 재고 #{s.id} ({s.label[:50]}) — 타오바오 {p.taobao_order_no}"
        await log_event(o, actor, "stock_used", f"{summary} 를 이 주문에 씀 (원래 {old.code if old else '-'})",
                        {"stock_id": s.id, "purchase_id": p.id, "from_order_id": old_order_id})
        if old:
            await log_event(old, actor, "stock_used", f"{summary} 를 {o.code} 에 씀 — 구매 기록이 그 주문으로 옮겨감",
                            {"stock_id": s.id, "purchase_id": p.id, "to_order_id": o.id})
        await restage(o, actor, "집운 재고를 이 주문에 씀")
        return await stock_dict(s)

    @staticmethod
    async def patch(stock_id: int, data: dict, auth: dict) -> dict:
        actor = actor_of(auth)
        s = await alive().get_or_none(id=stock_id)
        if not s:
            raise HTTPException(status_code=404, detail="재고를 찾지 못했습니다.")
        if not data:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        st = data.get("status")
        if st is not None:
            if st not in CLOSE_TO:
                raise HTTPException(status_code=400, detail="상태는 available · returned · written_off 중 하나예요 (쓰기는 /use).")
            if s.status == "used":
                raise HTTPException(status_code=409, detail="이미 다른 주문에 쓴 재고는 상태를 바꿀 수 없습니다.")
            s.status = st
            s.closed_at = None if st == "available" else datetime.now(timezone.utc)
        for k in ("label", "memo", "expires_on"):
            if k in data:
                setattr(s, k, data[k])
        await s.save()
        if st is not None and s.source_order_id:
            o = await MarketOrder.get_or_none(id=s.source_order_id)
            if o:
                await log_event(o, actor, "stock_changed", f"집운 재고 #{s.id} → {STATUS.get(st, st)}", {"stock_id": s.id, "status": st})
        return await stock_dict(s)

    @staticmethod
    async def delete(stock_id: int, auth: dict) -> None:
        s = await alive().get_or_none(id=stock_id)
        if not s:
            raise HTTPException(status_code=404, detail="재고를 찾지 못했습니다.")
        if s.status == "used":
            raise HTTPException(status_code=409, detail="이미 쓴 재고는 지울 수 없습니다.")
        s.deleted_at = datetime.now(timezone.utc)
        await s.save(update_fields=["deleted_at", "updated_at"])
