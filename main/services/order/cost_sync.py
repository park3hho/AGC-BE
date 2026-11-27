"""매입가 차이 기록 (2026-11-27 사용자 최종: "자동갱신도 하지 말고, 문제 있으면 가격에 문제 있었다고 이력 남기는 게 더 중요").

타오바오 구매가 저장 · 수정될 때 그 주문 옵션의 실구매 1단위가와 지금 매입가(product_option.price_cny)를 비교한다.
차이가 ±5% 이상이면 이슈 리포트(kind=cost_diff, '매입가 차이')와 option_cost_log(applied=False, reason='가격 문제 …')에 남긴다.
price_cny 는 바꾸지 않는다 — 고칠지는 사람이 (가격 책정 · 가격조사). 사람이 조사 가격을 고치면 option_cost_log 에 source=manual.

1단위가 = (paid_cny + Σ 수량 조건 할인 discounts[multi]) ÷ (seller_code 묶음 × 주문 수량). 옵션 = seller_code PR-…-{옵션id}x{묶음}.
비교하지 않는 구매: 한 주문에 구매 2건 이상(대체 구매) · 구성 다름 · 테스트 · 결제액 없음 · 환불 완료 · 삭제 · 옵션 못 읽음."""

import logging
from decimal import ROUND_HALF_UP, Decimal

from models.order.order import MarketOrder
from models.order.purchase import OptionCostLog, TaobaoPurchase
from services.order.stock_service import parse_sku

logger = logging.getLogger(__name__)
CENT = Decimal("0.01")
THRESHOLD = Decimal("0.05")   # ±5%


async def evaluate(p: TaobaoPurchase, o: MarketOrder | None = None) -> tuple[int | None, Decimal | None, str | None]:
    """구매 1건 → (옵션 id, 1단위가, 비교 안 하는 이유 | None)."""
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
    back = sum(Decimal(str(d.get("cny") or 0)) for d in (p.discounts or []) if d.get("multi"))
    return oid, ((Decimal(p.paid_cny) + back) / units).quantize(CENT, ROUND_HALF_UP), None


async def check_purchase(p: TaobaoPurchase, source: str = "auto") -> dict | None:
    """구매 1건 비교 → 차이가 ±5% 이상이면 이슈 · 이력. 돌려주는 값 = 이슈 dict 일부 (없으면 None)."""
    from models.product.price_survey import ProductOption
    from services.ops.issues import report
    if not p.order:
        await p.fetch_related("order")
    oid, unit, why = await evaluate(p, p.order)
    if why or not oid or unit is None:
        return None
    opt = await ProductOption.get_or_none(id=oid).prefetch_related("product")
    if not opt or opt.price_cny is None or Decimal(opt.price_cny) <= 0:
        return None
    rec = Decimal(opt.price_cny).quantize(CENT)
    diff = (unit - rec) / rec
    if abs(diff) < THRESHOLD:
        return None
    pct = int((diff * 100).quantize(Decimal("1"), ROUND_HALF_UP))
    direction = "비쌈" if diff > 0 else "쌈"
    reason = f"가격 문제 · 실구매가 {direction} {pct:+d}%"
    if not await OptionCostLog.filter(purchase_id=p.id, option_id=oid, applied=False, new_cny=unit, reason=reason).exists():
        await OptionCostLog.create(option_id=oid, purchase_id=p.id, order_id=p.order_id, old_cny=rec, new_cny=unit,
                                   applied=False, reason=reason, source=source)
    prod = getattr(opt, "product", None)
    pname = (getattr(prod, "title_ko", None) or getattr(prod, "title_cn", None) or "") if prod else ""
    oname = " / ".join(x for x in (opt.option1, opt.option2) if x)
    i, new = await report(
        "cost_diff", f"cost_diff:{p.id}:{oid}",
        title=f"{pname[:80]} · {oname[:60]} / {p.order.code or ''}",
        detail=f"실구매 ¥{unit} · 기록 ¥{rec} · {pct:+d}%",
        product_id=opt.product_id, option_id=oid, order_id=p.order_id, order_code=p.order.code, purchase_id=p.id,
        data={"unit_cny": str(unit), "recorded_cny": str(rec), "pct": pct, "direction": direction})
    return {"issue_id": i.id, "new": new, "option_id": oid, "pct": pct}


async def on_purchase(purchase_id: int) -> None:
    """구매 저장 · 수정 뒤 — 매입가는 바꾸지 않고 비교만. 실패해도 구매 저장은 살린다."""
    try:
        p = await TaobaoPurchase.get_or_none(id=purchase_id).prefetch_related("order")
        if p:
            r = await check_purchase(p)
            if r and r["new"]:
                logger.info(f"매입가 차이 이슈 {r['issue_id']} option={r['option_id']} {r['pct']:+d}% (구매 {purchase_id})")
    except Exception as e:
        logger.warning(f"매입가 비교 실패 purchase={purchase_id}: {type(e).__name__}: {e}")


async def log_manual_changes(before: dict[int, Decimal | None], after: dict[int, Decimal | None], reason: str) -> int:
    """사람이 조사 가격을 고쳐 price_cny 가 바뀐 옵션 → option_cost_log(source=manual, applied=True, 이전 → 새, 사유)."""
    n = 0
    for oid, new in after.items():
        old = before.get(oid)
        if new is not None and (old is None or Decimal(old).quantize(CENT) != Decimal(new).quantize(CENT)):
            await OptionCostLog.create(option_id=oid, purchase_id=0, old_cny=old, new_cny=new, applied=True,
                                       reason=reason[:100], source="manual")
            n += 1
    return n


async def backfill() -> dict:
    """비교 · 이력만 — 지금까지 구매 전부를 지금 매입가와 비교해 이슈를 남긴다 (매입가는 안 바꿈)."""
    checked, issues = 0, 0
    for p in await TaobaoPurchase.filter(deleted_at=None).prefetch_related("order"):
        checked += 1
        r = await check_purchase(p, source="backfill")
        issues += int(bool(r and r["new"]))
    return {"checked": checked, "new_issues": issues, "changed": []}
