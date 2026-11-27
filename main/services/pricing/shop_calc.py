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
        })
    return {"fx": f"{fx:.2f}", "rule": {"markup": "1.1", "pay_fee_pct": "3.52", "round_to": ROUND_TO,
                                        "divisor": DIVISOR}, "items": items, "total": len(items)}
