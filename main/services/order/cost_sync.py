"""매입가 = 최근 실구매 1단위가 (2026-11-27 사용자 "마지막 매입가 연동해", Manager2 전달).

타오바오 구매 기록이 생기거나 바뀌면(결제액 · 상품 · 환불 · 삭제) 그 주문 옵션의 product_option.price_cny 를
그 옵션의 '가장 최근' 유효 구매 1단위가로 맞춘다. 1단위가 = paid_cny ÷ (seller_code 묶음 × 주문 수량).
옵션 = seller_code PR-…-{옵션id}x{묶음}.

제외(갱신 안 함, 이력에 사유):
  ① 한 주문에 살아 있는 구매가 2건 이상 (대체 구매)   ② 구성이 다름 — items 수량 합 ≠ 묶음 × 주문 수량
  ③ 테스트 주문   ④ paid_cny 없음 · 0 · 환불 완료   (+ 옵션을 못 읽음)
쿠팡 · 네이버 판매가는 건드리지 않는다. 자사몰가(shop_sale_price)만 그 옵션을 바로 다시 계산한다.
이력 = option_cost_log (applied True/False)."""

import logging
from decimal import ROUND_HALF_UP, Decimal

from models.order.order import MarketOrder
from models.order.purchase import OptionCostLog, TaobaoPurchase
from services.order.stock_service import parse_sku

logger = logging.getLogger(__name__)
CENT = Decimal("0.01")


async def evaluate(p: TaobaoPurchase, o: MarketOrder | None = None) -> tuple[int | None, Decimal | None, str | None]:
    """구매 1건 → (옵션 id, 1단위가, 제외 사유 | None)."""
    o = o or await MarketOrder.get_or_none(id=p.order_id)
    if not o:
        return None, None, "주문 없음"
    _, oid, bundle = parse_sku(o.seller_code)
    if not oid:
        return None, None, "옵션 못 읽음"
    if o.is_test:
        return oid, None, "테스트 주문"
    if p.deleted_at:
        return oid, None, "삭제된 구매"
    if p.refund_status == "success":
        return oid, None, "환불 완료"
    if not p.paid_cny or Decimal(p.paid_cny) <= 0:
        return oid, None, "결제액 없음"
    alive = await TaobaoPurchase.filter(order_id=o.id, deleted_at=None).exclude(cn_status="cancelled").count()
    if alive >= 2:
        return oid, None, "한 주문 구매 2건 이상 (대체 구매)"
    units = max(1, int(bundle or 1)) * max(1, int(o.quantity or 1))
    got = sum(int(i.get("qty") or 0) for i in (p.items or []))
    if got and got != units:
        return oid, None, f"구성 다름 (산 수량 {got} ≠ 주문 단위 {units})"
    return oid, (Decimal(p.paid_cny) / units).quantize(CENT, ROUND_HALF_UP), None


def _when(p: TaobaoPurchase):
    return p.purchased_at or p.created_at


async def _log_once(**kw) -> None:
    """같은 구매 · 같은 결과는 한 번만 남긴다."""
    if not await OptionCostLog.filter(purchase_id=kw["purchase_id"], applied=kw["applied"], reason=kw.get("reason"),
                                      new_cny=kw.get("new_cny")).exists():
        await OptionCostLog.create(**kw)


async def sync_option(option_id: int, source: str = "auto") -> dict | None:
    """옵션의 가장 최근 유효 구매로 price_cny 맞추기. 바뀌면 {option_id, old, new, purchase_id}."""
    from models.product.price_survey import ProductOption
    best = None
    for p in await TaobaoPurchase.filter(order__seller_code__icontains=f"-{option_id}").prefetch_related("order"):
        oid, unit, why = await evaluate(p, p.order)
        if oid != option_id:
            continue
        if why:
            await _log_once(option_id=oid, purchase_id=p.id, order_id=p.order_id, applied=False, reason=why, source=source)
            continue
        if best is None or _when(p) > _when(best[0]):
            best = (p, unit)
    if not best:
        return None
    p, unit = best
    opt = await ProductOption.get_or_none(id=option_id)
    if not opt:
        return None
    old = Decimal(opt.price_cny) if opt.price_cny is not None else None
    if old is not None and old.quantize(CENT) == unit:
        return None
    opt.price_cny = unit
    await opt.save(update_fields=["price_cny", "updated_at"])
    await OptionCostLog.create(option_id=option_id, purchase_id=p.id, order_id=p.order_id, old_cny=old, new_cny=unit,
                               applied=True, source=source)
    await _shop_price(option_id, unit)
    return {"option_id": option_id, "old": old, "new": unit, "purchase_id": p.id}


async def _shop_price(option_id: int, cny: Decimal) -> None:
    """자사몰가도 그 옵션만 바로 (전체는 매일 환율 뒤 apply)."""
    try:
        from models.product.pricing import ShopSalePrice
        from services.pricing.exchange_rate_service import ExchangeRateService
        from services.pricing.shop_calc import shop_price
        sp = await ShopSalePrice.get_or_none(option_id=option_id)
        if sp:
            fx = await ExchangeRateService.current_rate()
            sp.price, sp.cost_cny, sp.fx = shop_price(cny * fx), cny, fx
            await sp.save()
    except Exception as e:
        logger.warning(f"자사몰가 갱신 실패 option={option_id}: {type(e).__name__}")


async def on_purchase(purchase_id: int) -> None:
    """구매 저장 · 수정 · 삭제 뒤 — 실패해도 구매 저장은 살린다. 같은 주문의 다른 구매(대체 구매 판정)도 같은 옵션이라 함께 맞춰진다."""
    try:
        p = await TaobaoPurchase.get_or_none(id=purchase_id).prefetch_related("order")
        if not p or not p.order:
            return
        _, oid, _ = parse_sku(p.order.seller_code)
        if oid:
            r = await sync_option(oid)
            if r:
                logger.info(f"매입가 갱신 option={oid} {r['old']}→{r['new']} (구매 {r['purchase_id']})")
    except Exception as e:
        logger.warning(f"매입가 갱신 실패 purchase={purchase_id}: {type(e).__name__}: {e}")


async def backfill() -> dict:
    """지금까지 구매 기록으로 옵션별 가장 최근 구매 기준 한 번 적용."""
    opts = set()
    for o in await MarketOrder.filter(taobao_purchases__id__isnull=False).distinct():
        _, oid, _ = parse_sku(o.seller_code)
        if oid:
            opts.add(oid)
    changed = []
    for oid in sorted(opts):
        r = await sync_option(oid, source="backfill")
        if r:
            changed.append(r)
    excluded = await OptionCostLog.filter(applied=False).count()
    return {"options": len(opts), "changed": changed, "excluded": excluded}
