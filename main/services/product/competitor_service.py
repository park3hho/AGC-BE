"""마켓 최저가 경쟁 — 우리 판매가 · 최소가(마진 바닥) · 그 마켓 최저가 판매자 · 그 가격 · 구매대행/국내 재고 (2026-11-07).

우리 판매가와 최소가는 가격 책정(ProductPricing · OptionPrice)과 현재 환율로 그때그때 계산한다.
경쟁자 쪽(CompetitorPrice)은 에이전트가 마켓 검색으로 넣고 매일 새벽 점검이 덮어쓴다."""
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException

from core.pricing_config import Platform
from models.order.order import MarketOrder
from models.order.purchase import TaobaoPurchase
from models.product.competitor import CompetitorPrice
from models.product.listing import MarketListing
from models.product.price_survey import PriceSurvey, PriceSurveyOption
from models.product.pricing import OptionPrice, ProductPricing
from models.product.product import Product
from schemas.competitor import CompetitorUpsert
from services.pricing.exchange_rate_service import ExchangeRateService
from services.pricing.shipping_service import option_shipping

PLATFORMS = ("coupang", "naver")
MARGIN_FLOOR_PCT = 5          # 쿠팡·네이버 마진 바닥 (가격 책정 규칙과 같음)
HISTORY_KEEP = 30


def _round_up_100(v: float) -> int:
    return int(math.ceil(v / 100 - 1e-9) * 100)


def _verdict(our: Optional[int], floor: Optional[int], c: Optional[CompetitorPrice]) -> str:
    """cheapest 우리가 최저 · only_us 우리만 · match 내려서 맞출 수 있음 · lose 최소가보다 싸서 못 맞춤 · unchecked 확인 전"""
    if not c:
        return "unchecked"
    if c.status == "only_us":
        return "only_us"
    if c.status == "not_found" or c.vendor_price is None or our is None:
        return "unchecked"
    if c.vendor_price >= our:
        return "cheapest"
    if floor is not None and c.vendor_price >= floor:
        return "match"
    return "lose"


def _comp_dict(c: Optional[CompetitorPrice]) -> Optional[dict]:
    if not c:
        return None
    return {"id": c.id, "status": c.status, "option_id": c.option_id, "vendor_name": c.vendor_name,
            "vendor_price": c.vendor_price, "vendor_shipping": c.vendor_shipping, "vendor_type": c.vendor_type,
            "vendor_note": c.vendor_note, "vendor_url": c.vendor_url, "query": c.query,
            "checked_at": c.checked_at.isoformat() if c.checked_at else None, "history": c.history or []}


class CompetitorService:
    @staticmethod
    async def list(platform: Optional[str] = None, q: Optional[str] = None) -> dict:
        fx = Decimal(str(await ExchangeRateService.current_rate()))
        listed = await MarketListing.filter(platform__in=list(PLATFORMS)).values("product_id", "platform")
        listed_set = {(r["product_id"], str(r["platform"].value if hasattr(r["platform"], "value") else r["platform"])) for r in listed}
        pids = sorted({p for p, _ in listed_set})
        qs = Product.filter(id__in=pids, deleted_at=None)
        if q:
            qs = qs.filter(title_ko__icontains=q.strip()) if not q.strip().upper().startswith("PR-") else qs.filter(code__icontains=q.strip())
        products = {p.id: p for p in await qs}
        pricings = await ProductPricing.filter(product_id__in=list(products), platform__in=[Platform.COUPANG, Platform.NAVER])
        pr_by = {(pr.product_id, pr.platform.value): pr for pr in pricings}
        ops = await OptionPrice.filter(pricing_id__in=[pr.id for pr in pricings], bundle_qty=1)
        op_by: dict[int, dict[int, int]] = {}
        for o in ops:
            op_by.setdefault(o.pricing_id, {})[o.option_id] = o.sale_price
        opt_ids = {oid for d in op_by.values() for oid in d}
        options = {o.id: o for o in await PriceSurveyOption.filter(id__in=list(opt_ids))}
        # 실제 구매가 — 쿠폰·할인으로 조사가보다 싸게 산 적이 있으면 그 위안을 원가에 쓴다 (옵션별 최근 1건, 1개 주문만)
        actual_cny: dict[int, float] = {}
        purchases = await TaobaoPurchase.filter(deleted_at=None).order_by("purchased_at").values("order_id", "paid_cny")
        po = {o.id: o for o in await MarketOrder.filter(id__in=[x["order_id"] for x in purchases])}
        for x in purchases:
            o = po.get(x["order_id"])
            sc = (o.seller_code or "") if o else ""
            last = sc.rsplit("-", 1)[-1] if sc else ""
            if last.isdigit() and (o.quantity or 1) == 1 and x["paid_cny"]:
                actual_cny[int(last)] = float(x["paid_cny"])
        sib_actual: dict[tuple, float] = {}
        for so in await PriceSurveyOption.filter(id__in=list(actual_cny)):
            sib_actual[(so.survey_id, str(so.price_cny))] = actual_cny[so.id]
        comps = await CompetitorPrice.filter(product_id__in=list(products))
        comp_by: dict[tuple, list[CompetitorPrice]] = {}
        for c in comps:
            comp_by.setdefault((c.product_id, c.platform), []).append(c)

        items, counts = [], {pf: {} for pf in PLATFORMS}
        for pid, p in sorted(products.items(), key=lambda kv: kv[1].code):
            row = {"product": {"id": p.id, "code": p.code, "title": p.title_ko or p.title_cn, "photo_url": p.photo_url,
                               "category": p.category}, "platforms": {}}
            for pf in PLATFORMS:
                if platform and pf != platform:
                    continue
                if (pid, pf) not in listed_set:
                    continue
                pr = pr_by.get((pid, pf))
                prices = op_by.get(pr.id, {}) if pr else {}
                fee = (float(pr.platform_fee_rate) + float(pr.payment_fee_rate)) / 100 if pr else None
                markup = 1 + float(pr.fx_markup_pct or 0) / 100 if pr else 1

                def calc(oid: int) -> dict:
                    o = options.get(oid)
                    our = prices.get(oid)
                    if not o or fee is None:
                        return {"option_id": oid, "our_price": our}
                    sh = option_shipping(o.option1, o.option2, p.category)
                    ship_cny = sh.get("shipping_cny")
                    if ship_cny is None:
                        return {"option_id": oid, "option": f"{o.option1} {o.option2 or ''}".strip(), "our_price": our}
                    sib = sib_actual.get((o.survey_id, str(o.price_cny)))   # 같은 조사·같은 조사가 형제 옵션(맛만 다름)의 실구매가
                    buy = actual_cny.get(oid, sib if sib is not None else float(o.price_cny))
                    basis = "actual" if oid in actual_cny else ("sibling" if sib is not None else "survey")
                    cost = (buy + float(ship_cny)) * float(fx) * markup
                    floor = _round_up_100(cost / (1 - fee - MARGIN_FLOOR_PCT / 100))
                    margin = round((our * (1 - fee) - cost) / our * 100, 1) if our else None
                    profit = round(our * (1 - fee) - cost) if our else None
                    return {"option_id": oid, "option": f"{o.option1} {o.option2 or ''}".strip(), "our_price": our,
                            "cost": round(cost), "min_price": floor, "margin_pct": margin, "profit": profit,
                            "buy_cny": buy, "survey_cny": float(o.price_cny), "ship_cny": float(ship_cny),
                            "cost_basis": basis}

                cl = comp_by.get((pid, pf), [])
                checks = []
                for c in sorted(cl, key=lambda x: (x.option_id or 0)):
                    oid = c.option_id or (min(prices, key=lambda k: prices[k]) if prices else None)
                    base = calc(oid) if oid else {"option_id": None, "our_price": None}
                    checks.append({**base, "competitor": _comp_dict(c),
                                   "verdict": _verdict(base.get("our_price"), base.get("min_price"), c)})
                if not checks:
                    oid = min(prices, key=lambda k: prices[k]) if prices else None
                    base = calc(oid) if oid else {"option_id": None, "our_price": None}
                    checks.append({**base, "competitor": None, "verdict": "unchecked"})
                main = sorted(checks, key=lambda x: ["lose", "match", "cheapest", "only_us", "unchecked"].index(x["verdict"]))[0]
                counts[pf][main["verdict"]] = counts[pf].get(main["verdict"], 0) + 1
                row["platforms"][pf] = {"main": main, "checks": checks, "option_count": len(prices)}
            if row["platforms"]:
                items.append(row)
        return {"items": items, "counts": counts, "fx": str(fx), "margin_floor_pct": MARGIN_FLOOR_PCT}

    @staticmethod
    async def upsert(body: CompetitorUpsert) -> dict:
        if not await Product.filter(id=body.product_id).exists():
            raise HTTPException(status_code=404, detail="제품을 찾지 못했습니다.")
        if body.option_id and not await PriceSurveyOption.filter(id=body.option_id, survey__product_id=body.product_id).exists():
            raise HTTPException(status_code=400, detail="이 제품의 옵션이 아닙니다.")
        at = body.checked_at or datetime.now(timezone.utc)
        c = await CompetitorPrice.get_or_none(product_id=body.product_id, platform=body.platform, option_id=body.option_id)
        vals = body.model_dump(exclude={"product_id", "platform", "option_id", "checked_at"})
        if body.status != "found":
            vals.update(vendor_name=vals.get("vendor_name"), vendor_price=None if body.status == "not_found" else vals.get("vendor_price"))
        snap = {"at": at.isoformat(), "status": body.status, "vendor_name": body.vendor_name,
                "vendor_price": body.vendor_price, "vendor_type": body.vendor_type}
        if c:
            hist = ([snap] + list(c.history or []))[:HISTORY_KEEP]
            await CompetitorPrice.filter(id=c.id).update(**vals, checked_at=at, history=hist)
            c = await CompetitorPrice.get(id=c.id)
        else:
            c = await CompetitorPrice.create(product_id=body.product_id, platform=body.platform, option_id=body.option_id,
                                             **vals, checked_at=at, history=[snap])
        return _comp_dict(c)

    @staticmethod
    async def delete(cid: int) -> None:
        n = await CompetitorPrice.filter(id=cid).delete()
        if not n:
            raise HTTPException(status_code=404, detail="기록을 찾지 못했습니다.")
