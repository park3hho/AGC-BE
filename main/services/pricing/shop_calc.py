"""자사몰 판매가 계산 (2026-11-27 사용자, Manager2 전달) — 가격 책정 › 자사몰 판매 화면. 계산 · 표시만 (저장 안 함).

- 자사몰은 기본 단위로만 판매 (조사 옵션 1개 = 1단위, 묶음 없음).
- 상품가 = 구매 원가(옵션 price_cny × 현재 환율) × 1.1 ÷ (1 − 0.0352), 100원 단위 올림
  → 결제수수료 3.52% 를 뺀 뒤에도 원가의 10% 가 남는 값.
- 운임은 여기서 안 셈 (주문 확정 때 장바구니 전체로 jiyun_estimate.estimate). 대신 옵션 1개 상자의 무게 · 크기 · 부피무게만 —
  실측(option_measure, 합포장 제외 · units 1) 우선, 없으면 jiyun_estimate.estimate_option 예측.
- 원가는 지금 price_cny (마지막 매입가 연동은 나중)."""

import math
from decimal import Decimal

from tortoise import Tortoise

from services.order.measure_service import measure_averages
from services.pricing import jiyun_estimate
from services.pricing.exchange_rate_service import ExchangeRateService

MARKUP = Decimal("1.1")          # 원가의 10% 남김
PAY_FEE = Decimal("0.0352")      # 결제수수료 3.2% + VAT
ROUND_TO = 100
DIVISOR = 6000                   # 부피무게 = 가로×세로×높이(cm) ÷ 6000 (kg)


def shop_price(cost_krw: Decimal) -> int:
    return int(math.ceil(cost_krw * MARKUP / (1 - PAY_FEE) / ROUND_TO) * ROUND_TO)


async def calc() -> dict:
    fx = await ExchangeRateService.current_rate()
    conn = Tortoise.get_connection("default")
    rows = await conn.execute_query_dict(
        """select p.id product_id, p.code, coalesce(p.title_ko, p.title_cn) title, p.photo_url, p.category,
                  o.id option_id, o.option1, o.option2, o.price_cny, o.sort,
                  exists (select 1 from market_listing ml where ml.product_id = p.id and ml.deleted_at is null) on_sale
           from product p join product_option o on o.product_id = p.id and o.deleted_at is null
           where p.deleted_at is null and o.price_cny is not null and o.price_cny > 0
           order by p.id desc, o.sort, o.id""")
    ids = [r["option_id"] for r in rows]
    meas = await measure_averages(ids)
    # 최근 실구매로 바뀐 매입가 (cost_sync, 2026-11-27) — 옵션별 마지막 갱신
    last = {r["option_id"]: r for r in await conn.execute_query_dict(
        """select distinct on (option_id) option_id, old_cny, new_cny, created_at from option_cost_log
           where applied order by option_id, id desc""")}
    ctx = await jiyun_estimate.load_context()
    items = []
    for r in rows:
        cny = Decimal(str(r["price_cny"]))
        cost = (cny * fx).quantize(Decimal("1"))
        price = shop_price(cny * fx)
        fee = (Decimal(price) * PAY_FEE).quantize(Decimal("1"))
        m = meas.get((r["option_id"], 1))
        if m:
            dims = [m["length_cm"], m["width_cm"], m["height_cm"]] if m["length_cm"] else None
            dim_g = round(dims[0] * dims[1] * dims[2] * 1000 / DIVISOR) if dims else None
            size = {"source": "measured", "count": m["count"], "weight_g": round(m["weight_kg"] * 1000),
                    "dims_cm": dims, "dim_g": dim_g, "note": f"실측 {m['count']}건"}
        else:
            e = jiyun_estimate.estimate_option(ctx, r["option_id"])
            src = "measured" if e["source"] == "measured" else "predicted"
            size = {"source": src, "count": 0, "weight_g": round(e["actual_g"]) if e.get("actual_g") else None,
                    "dims_cm": None, "dim_g": round(e["dim_g"]) if e.get("dim_g") else None, "note": e.get("note")}
        items.append({
            "product_id": r["product_id"], "code": r["code"], "title": r["title"], "photo_url": r["photo_url"],
            "category": r["category"], "on_sale": r["on_sale"], "option_id": r["option_id"],
            "option": " / ".join(x for x in (r["option1"], r["option2"]) if x),
            "cost_cny": f"{cny:.2f}", "cost_krw": int(cost), "price": price, "pay_fee": int(fee),
            "profit": int(price - fee - cost), **{"size": size},
            "last_buy": ({"old_cny": f"{last[r['option_id']]['old_cny']:.2f}" if last[r['option_id']]['old_cny'] is not None else None,
                          "new_cny": f"{last[r['option_id']]['new_cny']:.2f}",
                          "at": last[r['option_id']]['created_at'].isoformat()} if r["option_id"] in last else None),
        })
    return {"fx": f"{fx:.2f}", "rule": {"markup": "1.1", "pay_fee_pct": "3.52", "round_to": ROUND_TO,
                                        "divisor": DIVISOR}, "items": items, "total": len(items)}


async def apply() -> dict:
    """자사몰 판매가 저장 (2026-11-27 사용자: "전부 한번에" — 배송비 별도 전환). shop_sale_price 를 다시 채운다.
    대상 = 지금 자사몰 · 네이버 가격 책정에 들어 있는 옵션(묶음이었던 옵션도 기본 단위 1개로) 중 원가가 있는 것.
    매일 환율 받은 뒤 다시 돈다 (exchange_rate_service.fx_auto_loop). 바뀐 개수 · 빠진 개수를 돌려준다."""
    from models.product.pricing import ShopSalePrice
    fx = await ExchangeRateService.current_rate()
    conn = Tortoise.get_connection("default")
    rows = await conn.execute_query_dict(
        """select distinct o.id option_id, o.product_id, o.price_cny
           from public.product_pricing pp
           join public.option_price x on x.pricing_id = pp.id
           join public.product_option o on o.id = x.option_id and o.deleted_at is null
           join public.product p on p.id = o.product_id and p.deleted_at is null
           where pp.platform in ('shop', 'naver') and o.price_cny is not null and o.price_cny > 0""")
    old = {r.option_id: r for r in await ShopSalePrice.all()}
    keep, changed, added = set(), 0, 0
    for r in rows:
        cny = Decimal(str(r["price_cny"]))
        price = shop_price(cny * fx)
        keep.add(r["option_id"])
        cur = old.get(r["option_id"])
        if cur is None:
            await ShopSalePrice.create(option_id=r["option_id"], product_id=r["product_id"], price=price,
                                       cost_cny=cny, fx=fx)
            added += 1
        elif cur.price != price or cur.cost_cny != cny or cur.product_id != r["product_id"]:
            cur.price, cur.cost_cny, cur.fx, cur.product_id = price, cny, fx, r["product_id"]
            await cur.save()
            changed += 1
    gone = [i for i in old if i not in keep]
    if gone:
        await ShopSalePrice.filter(option_id__in=gone).delete()
    return {"fx": f"{fx:.2f}", "total": len(keep), "added": added, "changed": changed, "removed": len(gone)}
