"""매출 현황 (2026-11-10) — 주문 줄마다 매출 · 마켓 정산 · 타오바오 구매 · 집운비 · 이익 · 마진.

원가 규칙
- 구매·집운 기록이 있으면 그 원화(charged_krw)를 쓴다.
- 아직 없으면 추정: 구매 = 조사가 × 묶음 수, 집운 = 옵션 배송비 추정(묶음이면 묶음 운임) — 위안 × 202(알리페이 잔액 충전 환율).
  추정이 섞인 줄은 estimated=True.
- 취소·반품(stage cancelled)은 매출·정산 0. 타오바오 환불(memo '退款成功')이 안 된 구매만 손실로 남긴다.
- 테스트 주문(is_test)은 뺀다.
"""
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from models.order.jiyun import JiyunShipment
from models.order.order import MarketOrder
from models.order.purchase import TaobaoPurchase
from models.product.price_survey import PriceSurveyOption
from models.product.product import Product
from services.order.order_service import order_dict
from services.pricing.shipping_service import bundle_option_dict, option_shipping

KST = timezone(timedelta(hours=9))
EST_FX = Decimal("202")          # 알리페이 잔액 충전 환율 (원화 기록 규칙과 같음)
SKU_RE = re.compile(r"^(PR-\d{6}-[0-9A-Fa-f]{4})(?:-(\d+)(?:[xX](\d+))?)?$")
MARKET_LABEL = {"coupang": "쿠팡", "naver": "네이버", "shop": "자사몰"}


def _kst_date(dt: datetime | None) -> date | None:
    return dt.astimezone(KST).date() if dt else None


async def _estimate(o: MarketOrder, opt_cache: dict, prod_cache: dict) -> tuple[int | None, int | None]:
    """(구매 추정 원화, 집운 추정 원화) — 조사 옵션을 못 찾으면 None."""
    m = SKU_RE.match((o.seller_code or "").strip())
    if not m or not m.group(2):
        return None, None
    code, oid, n = m.group(1).upper(), int(m.group(2)), int(m.group(3) or 1)
    if oid not in opt_cache:
        opt_cache[oid] = await PriceSurveyOption.get_or_none(id=oid)
    opt = opt_cache[oid]
    if not opt:
        return None, None
    if code not in prod_cache:
        prod_cache[code] = await Product.get_or_none(code=code)
    cat = prod_cache[code].category if prod_cache[code] else "beverage"
    qty = max(1, o.quantity or 1)
    buy = Decimal(str(opt.price_cny or 0)) * n * qty
    sh = (bundle_option_dict(opt, n * qty, category=cat) if n * qty > 1 else option_shipping(opt.option1, opt.option2, cat))
    ship = sh.get("shipping_cny")
    return round(buy * EST_FX), (round(Decimal(str(ship)) * EST_FX) if ship is not None else None)


class SalesService:
    @staticmethod
    async def summary(date_from: date | None, date_to: date | None) -> dict:
        orders = await MarketOrder.filter(is_test=False).order_by("ordered_at")
        rows = []
        if date_from or date_to:
            orders = [o for o in orders if (d := _kst_date(o.ordered_at or o.created_at))
                      and (not date_from or d >= date_from) and (not date_to or d <= date_to)]
        ids = [o.id for o in orders]
        purchases, jiyuns = defaultdict(list), defaultdict(list)
        for p in await TaobaoPurchase.filter(order_id__in=ids, deleted_at=None):
            purchases[p.order_id].append(p)
        for j in await JiyunShipment.filter(order_id__in=ids, deleted_at=None):
            jiyuns[j.order_id].append(j)
        opt_cache, prod_cache = {}, {}

        for o in orders:
            amt = order_dict(o).get("amount") or {}
            cancelled = o.stage == "cancelled"
            ps, js = purchases.get(o.id, []), jiyuns.get(o.id, [])
            est_flags = []
            if cancelled:
                total = settle = 0
                purchase = sum(p.charged_krw or 0 for p in ps if "退款成功" not in (p.memo or ""))
                jiyun = sum(j.charged_krw or 0 for j in js if "退款成功" not in (j.memo or ""))
            else:
                total = amt.get("total") or o.total_price or 0
                settle = amt.get("settlement")
                if settle is None:
                    settle = total
                    est_flags.append("settlement")
                elif amt.get("estimated"):
                    est_flags.append("settlement")
                purchase = sum(p.charged_krw or 0 for p in ps)
                jiyun = sum(j.charged_krw or 0 for j in js)
                if not ps or not js:
                    eb, ej = await _estimate(o, opt_cache, prod_cache)
                    if not ps and eb is not None:
                        purchase, _ = eb, est_flags.append("purchase")
                    if not js and ej is not None:
                        jiyun, _ = ej, est_flags.append("jiyun")
                if any((p.charged_status or "none") == "none" for p in ps):
                    est_flags.append("card")
            profit = settle - purchase - jiyun
            m = SKU_RE.match((o.seller_code or "").strip())
            code = m.group(1).upper() if m else None
            rows.append({
                "id": o.id, "code": o.code, "order_no": o.order_no, "market": o.market, "date": str(_kst_date(o.ordered_at or o.created_at)),
                "product_code": code, "product_name": o.product_name, "option_name": o.option_name, "quantity": o.quantity,
                "stage": o.stage, "cancelled": cancelled, "claim_type": o.claim_type,
                "revenue": total, "settlement": settle, "purchase": purchase, "jiyun": jiyun, "profit": profit,
                "margin_pct": round(profit / total * 100, 1) if total else None,
                "estimated": est_flags,
            })

        def agg(rs: list[dict]) -> dict:
            live = [r for r in rs if not r["cancelled"]]
            s = lambda k: sum(r[k] for r in rs)
            revenue = s("revenue")
            return {
                "orders": len({(r["market"], r["order_no"] or r["code"]) for r in live}),
                "lines": len(live), "cancelled": len(rs) - len(live),
                "revenue": revenue, "settlement": s("settlement"), "purchase": s("purchase"), "jiyun": s("jiyun"),
                "profit": s("profit"), "margin_pct": round(s("profit") / revenue * 100, 1) if revenue else None,
                "estimated_lines": sum(1 for r in live if set(r["estimated"]) & {"purchase", "jiyun"}),
            }

        by_day = defaultdict(list)
        by_market = defaultdict(list)
        by_product = defaultdict(list)
        for r in rows:
            by_day[r["date"]].append(r)
            by_market[r["market"]].append(r)
            if not r["cancelled"]:
                by_product[r["product_code"] or r["product_name"]].append(r)
        titles = {}
        codes = [k for k in by_product if k and k.startswith("PR-")]
        for p in await Product.filter(code__in=codes):
            titles[p.code] = p.title_ko
        days = []
        if rows:
            d0 = date_from or min(date.fromisoformat(r["date"]) for r in rows)
            d1 = date_to or max(date.fromisoformat(r["date"]) for r in rows)
            d1 = min(d1, datetime.now(KST).date()) if not date_to else d1
            d = d0
            while d <= d1 and len(days) < 400:
                days.append({"date": str(d), **agg(by_day.get(str(d), []))})
                d += timedelta(days=1)
        products = sorted(
            ({"key": k, "title": titles.get(k) or by_product[k][0]["product_name"], **agg(v)} for k, v in by_product.items()),
            key=lambda x: -x["profit"])
        return {
            "range": {"from": str(date_from) if date_from else None, "to": str(date_to) if date_to else None},
            "total": agg(rows),
            "markets": [{"market": k, "label": MARKET_LABEL.get(k, k), **agg(v)} for k, v in sorted(by_market.items())],
            "days": days,
            "products": products,
            "orders": list(reversed(rows)),
        }
