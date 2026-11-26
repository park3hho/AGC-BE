"""집운 운임 예측 대조 (2026-11-26) — 지금까지 실제 집운 기록마다, 그 집운 '이전' 실측·요금 이력만으로 예측해 실제와 비교.

docker exec -w /app -e PYTHONPATH=/app agc_app python scripts/jiyun_backtest.py [/tmp/out.csv]
"""

import asyncio
import csv
import sys
from statistics import mean, median

from tortoise import Tortoise

from services.order.stock_service import parse_sku
from services.pricing import jiyun_estimate as je
from services.pricing.shipping_service import option_shipping


async def main(out_path: str | None):
    from database import TORTOISE_ORM
    await Tortoise.init(config=TORTOISE_ORM)
    conn = Tortoise.get_connection("default")
    rows = await conn.execute_query_dict(
        """select s.id, s.jiyun_no, s.weight_kg, s.fee_cny, s.bundle_id, s.memo, coalesce(s.requested_at, s.created_at) t,
                  o.id order_id, o.code, o.seller_code, o.quantity, coalesce(o.is_test,false) is_test
           from jiyun_shipment s left join market_order o on o.id = s.order_id
           where s.deleted_at is null and s.weight_kg is not null and s.fee_cny is not null order by t""")
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(je.base_no(r["jiyun_no"]), []).append(r)

    split: dict[int, int] = {}
    for b, rs in groups.items():
        for oid in {r["order_id"] for r in rs if r["order_id"]}:
            split[oid] = split.get(oid, 0) + 1
    full = await je.load_context()
    res = []
    for b, rs in groups.items():
        t = min(r["t"] for r in rs)
        orders = [r for r in rs if r["order_id"]]
        items = je.items_from_orders([{"id": r["order_id"], "seller_code": r["seller_code"], "quantity": r["quantity"]} for r in orders], split)
        if not items:
            continue
        act_fee = round(sum(float(r["fee_cny"]) for r in rs), 2)
        act_kg = round(sum(float(r["weight_kg"]) for r in rs), 3)
        ctx = await je.load_context(before=t, exclude_base=b)      # 그 집운 이전 정보만
        e = je.estimate(ctx, items)
        # 예전 방식: 옵션 이름 추정 + 식품 요율
        old_g = 0.0
        for oid, units in items:
            o = full.opts.get(oid)
            if o:
                sh = option_shipping(o.option1 or "", o.option2, o.category)
                g = max(sh.get("weight_g") or 0, sh.get("dim_weight_g") or 0)
                old_g += (g - 500) * units + 500 if g else 0
        actual_rate = je.rate_of(act_kg, act_fee) if len(rs) == 1 else None
        # 예외 (2026-11-26 사용자 "예외 고려해서 다시")
        exc = []
        if any(r["order_id"] and not parse_sku(r["seller_code"])[1] for r in rs):
            exc.append("SKU 못 읽음(일부 물건 빠짐)")
        if act_kg > je.MAX_KG:
            exc.append("30kg 넘어 대형 요금으로 한 번에 보냄(지금 규칙은 나눠 보냄)")
        if "확인 필요" in " ".join((r.get("memo") or "") for r in rs):
            exc.append("기록 이상(당시 확인 필요 표시)")
        cold = bool(actual_rate) and e["rate"] != actual_rate
        # 요금표를 알았다면(처음 보내는 제품의 요금표는 미리 모름) 얼마였을지
        fee_rate_known = (e["fee_cny_general"] if actual_rate == "general" else e["fee_cny_food"]) if cold else e["fee_cny"]
        res.append({
            "jiyun": b, "date": t.strftime("%m-%d"), "orders": "+".join(sorted({r["code"] for r in orders})),
            "items": "; ".join(f"{(l['title'] or '')[:18]} {l['label'][:22] if l['label'] else ''} ×{l['units']}" for l in e["items"]),
            "basis": "/".join(e["basis"]), "rate_pred": e["rate"], "rate_actual": actual_rate or "",
            "kg_pred": round(e["weight_g"] / 1000, 2), "kg_actual": act_kg,
            "fee_pred": e["fee_cny"], "fee_sum_max": e["fee_cny_sum_max"], "fee_actual": act_fee,
            "diff": round(e["fee_cny"] - act_fee, 2),
            "fee_old": je.fee_cny(old_g, "food") if old_g else None,
            "diff_old": round(je.fee_cny(old_g, "food") - act_fee, 2) if old_g else None,
            "test": rs[0]["is_test"],
            "exception": " / ".join(exc), "rate_cold_miss": cold,
            "diff_rate_known": round(fee_rate_known - act_fee, 2),
        })

    def summary(rs, key):
        d = [r[key] for r in rs if r[key] is not None]
        if not d:
            return "-"
        exact = sum(1 for x in d if abs(x) < 0.01)
        within = sum(1 for x in d if abs(x) <= 4)
        return (f"n={len(d)} 정확일치 {exact} · ±¥4 이내 {within} · 평균오차 ¥{mean(abs(x) for x in d):.2f}"
                f" · 적게잡음 {sum(1 for x in d if x < -0.01)} 많이잡음 {sum(1 for x in d if x > 0.01)}")

    print("집운", len(res))
    ok = [r for r in res if not r["exception"]]
    print("== 예외 빼고 ==", len(ok))
    print("새 방식:", summary(ok, "diff"))
    print("새 방식(요금표 알 때):", summary(ok, "diff_rate_known"))
    print("예전 방식:", summary(ok, "diff_old"))
    for src in ("measured", "product", "predicted"):
        sub = [r for r in ok if r["basis"] == src]
        if sub:
            print(f"  [{src}] {summary(sub, 'diff')} | 요금표 알 때 {summary(sub, 'diff_rate_known')}")
    sub = [r for r in ok if "/" in r["basis"]]
    if sub:
        print(f"  [섞임] {summary(sub, 'diff')}")
    for r in res:
        if r["exception"]:
            print("  예외:", r["jiyun"][-6:], r["orders"], r["fee_pred"], r["fee_actual"], r["exception"])
    print("  처음 보낸 제품 요금표 빗나감:", [(r["jiyun"][-6:], r["diff"]) for r in ok if r["rate_cold_miss"]])
    print("  예외 빼고 큰 오차:")
    for r in sorted(ok, key=lambda r: -abs(r["diff_rate_known"]))[:8]:
        print("   ", r["jiyun"][-6:], r["date"], r["basis"], r["kg_pred"], r["kg_actual"], r["fee_pred"], r["fee_actual"], r["diff_rate_known"], "|", r["items"][:60])
    print("== 전체 ==")
    print("새 방식:", summary(res, "diff"))
    print("예전 방식:", summary(res, "diff_old"))
    for src in ("measured", "product", "predicted", "fallback"):
        sub = [r for r in res if r["basis"] == src]
        if sub:
            print(f"  [{src}] {summary(sub, 'diff')}")
    mixed = [r for r in res if "/" in r["basis"]]
    if mixed:
        print(f"  [섞임] {summary(mixed, 'diff')}")
    rp = [r for r in res if r["rate_actual"]]
    print("요금표 맞힘:", sum(1 for r in rp if r["rate_pred"] == r["rate_actual"]), "/", len(rp))
    kerr = [abs(r["kg_pred"] - r["kg_actual"]) / r["kg_actual"] for r in res if r["kg_actual"]]
    print(f"무게 오차 중앙값 {median(kerr)*100:.1f}% · 평균 {mean(kerr)*100:.1f}%")
    if out_path:
        with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(res[0].keys()))
            w.writeheader()
            w.writerows(res)
    for r in sorted(res, key=lambda r: -abs(r["diff"]))[:15]:
        print(r["jiyun"][-6:], r["date"], r["basis"], r["rate_pred"], r["rate_actual"], r["kg_pred"], r["kg_actual"],
              r["fee_pred"], r["fee_actual"], r["diff"], "|", r["items"][:70])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
