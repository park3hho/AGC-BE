"""집운 운임 예측 (2026-11-26 사용자: "주문이 오면 무게·크기로 어떤 가격으로 잡힐지, 물건 추가하면 운임이 어떻게 늘지").

원칙 — 쌓아 온 실측(option_measure)으로 계산하고, 없는 것은 예측한다.

요금 (실제 집운 55건 중 54건 1위안 단위 일치, 2026-11-26 대조)
  계산 무게 = 실제 무게와 부피 무게(가로×세로×높이 ÷ 6000) 중 큰 값
  1kg 이하는 1kg, 넘는 무게는 0.5kg 단위 올림 · 첫 1kg 요금 + 0.5kg 마다 ¥2
  첫 1kg 요금: 식품(食品敏货) ¥33 · 일반(普货) ¥21.5 — 창고가 정한다.
  → 처음 보내는 제품은 식품(비싼 쪽), 그 제품만 든 집운이 일반 요금으로 나온 적 있으면 일반.

옵션 1개(조사 옵션 1개 = units 1)의 무게 — 위에서부터 먼저 있는 것
  1. measured  같은 옵션 실측(합포장 아님) — 상자 1개당 무게·부피의 중앙값
  2. product   같은 제품 다른 옵션 실측 — 용량 비율로 환산
  3. predicted 카테고리 모델 — 실측 전체로 맞춘 '용량 1ml 당 무게'(+상자 무게) · '용량 1ml 당 부피무게'
               옵션에 상자 크기(cm)가 적혀 있으면 그 부피 무게를 쓴다
  4. fallback  용량도 못 읽으면 예전 계산(services/pricing/shipping_service.option_shipping)

여러 개(묶음·합포장): 실제 무게 합, 부피 무게 합 → 계산 무게 = 둘 중 큰 값.
보수적으로 '상자마다 큰 값의 합'(sum_max)도 함께 내려준다.
"""

from __future__ import annotations

import math
import re
from itertools import product
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median
from typing import Iterable, Optional

from tortoise import Tortoise

from services.order.stock_service import parse_sku
from services.pricing.shipping_service import option_shipping, option_volume_ml
from utils.volume import parse_box_cm, parse_box_per

DIVISOR = 6000
FIRST_KG = 1.0
STEP_KG = 0.5
STEP_CNY = 2.0
FIRST_CNY = {"food": 33.0, "general": 21.5}
BOX_G = 500           # 상자 1개 무게 가정 (카테고리 모델의 절편)
CARTON_ML = 3000      # 이 용량 이상인 옵션은 옵션 1개 = 상자 1개 (음료 박스). 작은 것은 여러 개가 한 상자에 → 상자 무게 한 번만
NONBEV_K_MAX = 1.5    # 음료 아닌 것(차·과자)의 용량 1ml(=1g)당 실제 무게 상한 — 실측이 적어 튀는 값 방지
MAX_KG = 30.0
MARGIN = 1.01         # 예측 무게에 1% 여유 — 실측 8.50kg 가 다음에 8.52kg 로 재져 한 칸(¥2) 올라간 사례(레몬티 2건)
_SUFFIX = re.compile(r"-\d+$")


def base_no(no: Optional[str]) -> str:
    return _SUFFIX.sub("", (no or "").strip())


def billable_kg(weight_g: float) -> float:
    kg = max(0.0, weight_g) / 1000
    if kg <= FIRST_KG:
        return FIRST_KG
    return FIRST_KG + math.ceil(round((kg - FIRST_KG) / STEP_KG, 6)) * STEP_KG


# 안전 기본요금 (2026-11-27 사용자 "33위안부터 시작하는데 안전하게 40위안부터") — 가격 계산·자사몰 배송비는 첫 1kg 을 ¥40 으로.
# 실제 타오바오 요금표(FIRST_CNY)는 실제 집운 기록 판별(rate_of)·대조(tariff=True)에만 쓴다.
SAFE_FIRST_CNY = 40.0


def fee_cny(weight_g: float, rate: str = "food", tariff: bool = False) -> float:
    b = billable_kg(weight_g)
    first = FIRST_CNY[rate] if tariff else max(FIRST_CNY[rate], SAFE_FIRST_CNY)
    return first + (b - FIRST_KG) / STEP_KG * STEP_CNY


def rate_of(weight_kg: float, fee: float) -> Optional[str]:
    """실제 집운 무게·요금이 어느 요금표와 맞는지 (무게 반올림 오차로 한 칸 위도 허용)."""
    g = float(weight_kg) * 1000
    for r in ("food", "general"):
        if abs(fee_cny(g, r, True) - fee) < 0.01 or abs(fee_cny(g + 10, r, True) - fee) < 0.01:
            return r
    return None


@dataclass
class Opt:
    id: int
    product_id: int
    category: str
    title: str
    label: str
    volume_ml: Optional[int]
    box_dim_g: Optional[float]        # 옵션 이름에 적힌 상자의 부피무게(옵션 1개분)
    option1: Optional[str] = None
    option2: Optional[str] = None


@dataclass
class Ctx:
    opts: dict[int, Opt] = field(default_factory=dict)
    meas: list[dict] = field(default_factory=list)          # 합포장 아닌 실측 (옵션 1개분으로 나눈 값)
    rate_by_product: dict[int, str] = field(default_factory=dict)
    k_actual: dict[str, float] = field(default_factory=dict)   # 카테고리별 (실제무게 − 상자) / 용량
    k_dim: dict[str, float] = field(default_factory=dict)      # 음료: 부피무게 / 용량
    dim_abs: dict[str, float] = field(default_factory=dict)    # 차·과자: 상자 1개 부피무게 중앙값(g)
    k_dim_nb: dict[str, float] = field(default_factory=dict)   # 차·과자: 부피무게 / 용량


async def _opts(conn) -> dict[int, Opt]:
    rows = await conn.execute_query_dict(
        """select o.id, o.product_id, o.option1, o.option2, o.unit_amount, o.unit, o.total_count, o.unit_count, o.pack_count,
                  coalesce(p.category,'beverage') category, p.title_ko
           from product_option o join product p on p.id = o.product_id""")
    out = {}
    for r in rows:
        box_text = r["option2"] if parse_box_cm(r["option2"]) else r["option1"]
        box = parse_box_cm(box_text)
        box_dim = None
        if box:
            a, b, c = box
            box_dim = float(a) * float(b) * float(c) * 1000 / DIVISOR / max(1, parse_box_per(box_text))
        out[r["id"]] = Opt(r["id"], r["product_id"], r["category"], r["title_ko"] or "",
                           " ".join(x for x in (r["option1"], r["option2"]) if x)[:80],
                           option_volume_ml(r["option1"], r["option2"], r), box_dim, r["option1"], r["option2"])
    return out


async def load_context(before: Optional[datetime] = None, exclude_base: Optional[str] = None) -> Ctx:
    """실측·요금 이력으로 계산 준비. before 를 주면 그 시각 전 기록만 (대조용 — 미래 정보를 쓰지 않게)."""
    conn = Tortoise.get_connection("default")
    ctx = Ctx(opts=await _opts(conn))
    rows = await conn.execute_query_dict(
        """select m.option_id, m.product_id, m.units, m.mixed, m.weight_kg, m.length_cm, m.width_cm, m.height_cm, m.jiyun_no,
                  coalesce(j.requested_at, j.created_at, m.measured_at, m.created_at) t
           from option_measure m left join jiyun_shipment j on j.id = m.jiyun_id
           where m.deleted_at is null and m.weight_kg is not null""")
    for r in rows:
        if r["mixed"] or not r["option_id"]:
            continue
        if before and r["t"] and r["t"] >= before:
            continue
        if exclude_base and base_no(r["jiyun_no"]) == exclude_base:
            continue
        u = max(1, r["units"] or 1)
        dim = None
        if r["length_cm"] and r["width_cm"] and r["height_cm"]:
            dim = float(r["length_cm"]) * float(r["width_cm"]) * float(r["height_cm"]) * 1000 / DIVISOR / u
        ctx.meas.append({"option_id": r["option_id"], "product_id": r["product_id"],
                         "actual_g": float(r["weight_kg"]) * 1000 / u, "dim_g": dim})

    # 요금 이력 — 한 제품만 든 집운(합포장 아님)의 요금표
    ships = await conn.execute_query_dict(
        """select s.jiyun_no, s.weight_kg, s.fee_cny, coalesce(s.requested_at, s.created_at) t, o.seller_code
           from jiyun_shipment s join market_order o on o.id = s.order_id
           where s.deleted_at is null and s.weight_kg is not null and s.fee_cny is not null""")
    groups: dict[str, list] = {}
    for s in ships:
        groups.setdefault(base_no(s["jiyun_no"]), []).append(s)
    for b, ss in groups.items():
        if b == exclude_base or len(ss) != 1:
            continue
        s = ss[0]
        if before and s["t"] and s["t"] >= before:
            continue
        _, oid, _ = parse_sku(s["seller_code"])
        o = ctx.opts.get(oid)
        r = rate_of(float(s["weight_kg"]), float(s["fee_cny"]))
        if o and r:
            # 식품이 한 번이라도 나오면 식품 (보수적)
            if ctx.rate_by_product.get(o.product_id) != "food":
                ctx.rate_by_product[o.product_id] = r

    # 카테고리 모델
    ka: dict[str, list] = {}
    kd: dict[str, list] = {}
    for m in ctx.meas:
        o = ctx.opts.get(m["option_id"])
        if not o or not o.volume_ml:
            continue
        ka.setdefault(o.category, []).append(max(0.0, m["actual_g"] - BOX_G) / o.volume_ml)
        if m["dim_g"]:
            kd.setdefault(o.category, []).append(m["dim_g"] / o.volume_ml)
    ctx.k_actual = {c: (median(v) if c == "beverage" else min(NONBEV_K_MAX, max(1.0, median(v)))) for c, v in ka.items()}
    ctx.k_dim = {c: median(v) for c, v in kd.items() if c == "beverage"}
    # 차·과자는 내용물 무게와 상자 크기가 비례하지 않아 '상자 1개 부피무게'의 중앙값을 그대로 쓴다
    da: dict[str, list] = {}
    for m in ctx.meas:
        o = ctx.opts.get(m["option_id"])
        if o and o.category != "beverage" and m["dim_g"]:
            da.setdefault(o.category, []).append(m["dim_g"])
    ctx.dim_abs = {c: median(v) for c, v in da.items()}
    # 작은 낱개를 여러 개 묶으면 상자는 하나, 부피는 내용물에 비례 — '용량 1g당 부피무게'(차·과자) (2026-11-27)
    ctx.k_dim_nb = {c: median(v) for c, v in kd.items() if c == "other"}   # 차(tea)는 잎 무게와 상자 크기가 무관 → 상자 하나 값만
    return ctx


def _med(vals: Iterable[Optional[float]]) -> Optional[float]:
    v = [x for x in vals if x]
    return median(v) if v else None


def estimate_option(ctx: Ctx, option_id: int) -> dict:
    """옵션 1개(상자 1개)의 {actual_g, dim_g, source, note}."""
    o = ctx.opts.get(option_id)
    if not o:
        return {"actual_g": None, "dim_g": None, "source": "unknown", "note": "옵션 없음"}
    own = [m for m in ctx.meas if m["option_id"] == option_id]
    if own:
        return {"actual_g": _med(m["actual_g"] for m in own), "dim_g": _med(m["dim_g"] for m in own) or o.box_dim_g,
                "source": "measured", "note": f"실측 {len(own)}건"}
    sib = [m for m in ctx.meas if m["product_id"] == o.product_id and ctx.opts.get(m["option_id"]) and ctx.opts[m["option_id"]].volume_ml]
    if sib and o.volume_ml:
        ra = _med(max(0.0, m["actual_g"] - BOX_G) / ctx.opts[m["option_id"]].volume_ml for m in sib) or ctx.k_actual.get(o.category, 1.0)
        rd = _med((m["dim_g"] or 0) / ctx.opts[m["option_id"]].volume_ml for m in sib)
        return {"actual_g": o.volume_ml * ra + BOX_G, "dim_g": (o.volume_ml * rd if rd else None) or o.box_dim_g,
                "source": "product", "note": f"같은 제품 다른 옵션 실측 {len(sib)}건 · 용량 비율"}
    if o.volume_ml:
        ka = ctx.k_actual.get(o.category, 1.0)
        kd = ctx.k_dim.get(o.category)
        dim = o.box_dim_g if o.box_dim_g else (o.volume_ml * kd if kd else ctx.dim_abs.get(o.category))
        if dim is None and o.category != "beverage":
            sh = option_shipping(o.option1 or "", o.option2, o.category)
            dim = sh.get("dim_weight_g")
        carton = o.volume_ml >= CARTON_ML
        shared = {}
        if not carton and not o.box_dim_g and o.category != "beverage":
            # 상자 하나(dim_once)를 여러 개가 나눠 쓰고, 개수만큼은 내용물 비례 부피(dim_g)로 더한다
            knb = ctx.k_dim_nb.get(o.category)
            shared = {"dim_once_g": dim or 0}
            dim = o.volume_ml * knb if knb else 0
            # 무거운 과자(비스킷 800g 등)는 가벼운 봉지칩 비율로 부피가 과하게 커지므로, 한 개분은 실측 상자 1개(중앙값)를 넘지 않게
            if shared["dim_once_g"]:
                dim = min(dim, shared["dim_once_g"])
        return {"actual_g": o.volume_ml * ka + (BOX_G if carton else 0), "box_once_g": 0 if carton else BOX_G,
                "dim_g": dim, "source": "predicted", **shared,
                "note": f"{o.category} 모델 · 1ml당 {ka:.2f}g" + (f" · 부피 1ml당 {kd:.2f}g" if kd and not o.box_dim_g else "")
                        + (" · 옵션 상자 크기" if o.box_dim_g else "")}
    sh = option_shipping(o.option1 or "", o.option2, o.category)
    return {"actual_g": sh.get("weight_g"), "dim_g": sh.get("dim_weight_g"), "source": "fallback", "note": "용량을 못 읽음 · 최소 상자 가정"}


def estimate(ctx: Ctx, items: list[tuple[int, int]]) -> dict:
    """items = [(option_id, units)] — 한 집운(한 상자 또는 합포장)으로 갈 것. 요금·무게 예측."""
    lines, act, dim, smax = [], 0.0, 0.0, 0.0
    rates = set()
    box_once = 0.0
    dim_once, dim_small = 0.0, 0.0
    for oid, units in items:
        e = estimate_option(ctx, oid)
        a = (e["actual_g"] or 0) * units
        box_once = max(box_once, e.get("box_once_g") or 0)
        d = (e["dim_g"] or 0) * units
        if "dim_once_g" in e:
            dim_once = max(dim_once, e["dim_once_g"])
            dim_small += d
            act, smax = act + a, smax + a
        else:
            act, dim, smax = act + a, dim + d, smax + max(a, d)
        o = ctx.opts.get(oid)
        rates.add(ctx.rate_by_product.get(o.product_id, "food") if o else "food")
        lines.append({"option_id": oid, "units": units, "title": o.title[:40] if o else None, "label": o.label if o else None,
                      "actual_g": round(a), "dim_g": round(d) if d else None, "source": e["source"], "note": e["note"]})
    rate = "general" if rates == {"general"} else "food"
    act += box_once
    smax += box_once
    if dim_once or dim_small:
        small = max(dim_once, dim_small)
        dim += small
        smax = max(smax, act, dim)
    w = max(act, dim) * MARGIN
    smax *= MARGIN
    fee = fee_cny(w, rate)
    parts = 1
    if w / 1000 > MAX_KG:
        # 30kg 넘으면 대형 요금(실제 41.45kg → ¥270)이라 비싸다 → 30kg 이하로 나눠 보내는 값으로 계산
        parts = math.ceil(w / 1000 / MAX_KG)
        fee = fee_cny(w / parts, rate) * parts
    return {
        "items": lines, "rate": rate,
        "actual_g": round(act), "dim_g": round(dim) if dim else None, "weight_g": round(w),
        "billable_kg": billable_kg(w), "fee_cny": fee, "parts": parts,
        "fee_cny_sum_max": fee_cny(smax, rate),          # 상자마다 큰 값 합 (보수적)
        "fee_cny_food": fee_cny(w, "food"), "fee_cny_general": fee_cny(w, "general"),
        # 실제 타오바오 요금표 기준(안전 기본요금 ¥40 없이) — 실제 집운 대조용
        "tariff_cny": (fee_cny(w / parts, rate, True) * parts),
        "tariff_cny_food": fee_cny(w, "food", True), "tariff_cny_general": fee_cny(w, "general", True),
        "over_limit": w / 1000 > MAX_KG,
        "basis": sorted({l["source"] for l in lines}),
    }


# ── 상자 구성 최적화 (2026-11-27 사용자 "최저가를 계산해야") ──────────────────────────────────────
# 상자마다 첫 1kg 기본요금(식품 ¥33)을 다시 받는다 → 상자 하나 ≈ ¥29 + ¥4×kg.
#   목표: 쪼갤 수 없는 단위(옵션 1개)를 30kg 이하 상자들로 나눠 Σ 상자 요금 최소.
#   상자 하나의 무게·요금은 estimate(그 상자에 든 단위) 그대로 (상자 무게 · 부피 모델 같이 씁).
#   후보: 한 상자(30kg 넘으면 대형 수수료) · n0 = ⌈W/30⌉ 상자 · n0+1 상자. 단위 10개 이하는 전수 비교, 많으면 탐욕 + 교환 개선.
OVERSIZE_CNY = 75.0      # 30kg 넘는 한 상자 대형 수수료 추정 (실측 41.45kg → ¥270, 일반 식 ¥195)
EXACT_MAX_UNITS = 10
OVERSIZE_MAX_KG = 45.0   # 30kg 넘는 한 상자는 실제로 보낸 적 있는 무게(41.45kg) 근처까지만 후보 — 그 이상은 상한을 몰라 나눠 보냄


def _pack_key(units: list[int]) -> tuple:
    return tuple(sorted(units))


def pack(ctx: Ctx, items: list[tuple[int, int]]) -> dict:
    """items = [(option_id, units)] → 가장 싼 상자 구성 {fee_cny, boxes:[{items, weight_g, billable_kg, fee_cny}], weight_g, parts, oversize}.
    30kg 이하면 한 상자가 항상 최저 (상자를 늘리면 기본요금만큼 비싼다)."""
    units = [oid for oid, n in items for _ in range(max(0, n))]
    if not units:
        return {"fee_cny": 0.0, "boxes": [], "weight_g": 0, "parts": 0, "oversize": False}
    cache: dict[tuple, dict] = {}

    def box(us: list[int]) -> dict:
        k = _pack_key(us)
        if k not in cache:
            cnt: dict[int, int] = {}
            for u in us:
                cnt[u] = cnt.get(u, 0) + 1
            e = estimate(ctx, list(cnt.items()))
            w = e["weight_g"]
            f = fee_cny(w, e["rate"]) + (OVERSIZE_CNY if w / 1000 > MAX_KG else 0)
            cache[k] = {"items": sorted(cnt.items()), "weight_g": w, "billable_kg": billable_kg(w), "fee_cny": f,
                        "rate": e["rate"], "over": w / 1000 > MAX_KG}
        return cache[k]

    whole = box(units)
    if not whole["over"]:
        return {"fee_cny": whole["fee_cny"], "boxes": [whole], "weight_g": whole["weight_g"], "parts": 1, "oversize": False}

    def total(bs: list[list[int]]) -> float:
        return sum(box(b)["fee_cny"] for b in bs)

    def ok(bs: list[list[int]]) -> bool:
        return all(b and not box(b)["over"] for b in bs)

    def exact(n: int):
        best = None
        for assign in product(range(n), repeat=len(units) - 1):
            bs: list[list[int]] = [[] for _ in range(n)]
            bs[0].append(units[0])
            for u, k in zip(units[1:], assign):
                bs[k].append(u)
            if not ok(bs):
                continue
            c = total(bs)
            if best is None or c < best[0] - 1e-9:
                best = (c, bs)
        return best

    def greedy(n: int):
        bs: list[list[int]] = [[] for _ in range(n)]
        for u in sorted(units, key=lambda u: -box([u])["weight_g"]):
            cand = [k for k in range(n) if not box(bs[k] + [u])["over"]]
            if not cand:
                return None
            k = min(cand, key=lambda k: box(bs[k] + [u])["fee_cny"] - (box(bs[k])["fee_cny"] if bs[k] else 0))
            bs[k].append(u)
        improved = True
        while improved:
            improved = False
            for i in range(n):
                for j in range(n):
                    if i == j or improved:
                        continue
                    for xi, x in enumerate(bs[i]):
                        for y in [None, *bs[j]]:
                            bi = bs[i][:xi] + bs[i][xi + 1:] + ([y] if y is not None else [])
                            bj = list(bs[j])
                            if y is not None:
                                bj.remove(y)
                            bj.append(x)
                            if ok([bi, bj]) and total([bi, bj]) < total([bs[i], bs[j]]) - 1e-9:
                                bs[i], bs[j], improved = bi, bj, True
                                break
                        if improved:
                            break
        return (total(bs), bs) if ok(bs) else None

    n0 = max(2, math.ceil(whole["weight_g"] / 1000 / MAX_KG))
    options = [(whole["fee_cny"], [units])] if whole["weight_g"] / 1000 <= OVERSIZE_MAX_KG else []
    found_at = None
    for n in range(n0, len(units) + 1):   # 쪼갤 수 없는 단위라 ⌈W/30⌉ 상자에 안 들어갈 수 있다 → 들어가는 가장 적은 n 과 n+1
        if found_at is not None and n > found_at + 1:
            break
        r = exact(n) if len(units) <= EXACT_MAX_UNITS and n ** (len(units) - 1) <= 200_000 else greedy(n)
        if r:
            options.append(r)
            found_at = n if found_at is None else found_at
    if not options:   # 이론상 없음 (단위 하나가 30kg 넘는 경우) — 한 상자로
        options = [(whole["fee_cny"], [units])]
    fee, bs = min(options, key=lambda r: r[0])
    boxes = [box(b) for b in bs]
    return {"fee_cny": round(fee, 2), "boxes": boxes, "weight_g": sum(b["weight_g"] for b in boxes),
            "parts": len(boxes), "oversize": any(b["over"] for b in boxes)}


def marginal(ctx: Ctx, current: list[tuple[int, int]], add: list[tuple[int, int]]) -> dict:
    """지금 묶음에 add 를 더하면 운임이 얼마 늘어나는지."""
    a = estimate(ctx, current) if current else None
    b = estimate(ctx, current + add)
    base = a["fee_cny"] if a else 0.0
    return {"before": a, "after": b, "added_cny": round(b["fee_cny"] - base, 2),
            "alone_cny": estimate(ctx, add)["fee_cny"]}


def items_from_orders(orders: Iterable[dict], split: Optional[dict[int, int]] = None) -> list[tuple[int, int]]:
    """market_order dict(id, seller_code, quantity) → [(option_id, units)]. 같은 주문은 한 번만.
    split = {주문 id: 그 주문이 나뉘어 간 집운 수} — 나눠 보낸 주문은 집운 하나에 그만큼 나눈 개수만 든다."""
    out, seen = [], set()
    for o in orders:
        if o.get("id") in seen:
            continue
        seen.add(o.get("id"))
        _, oid, bq = parse_sku(o.get("seller_code"))
        if oid:
            u = bq * max(1, o.get("quantity") or 1)
            n = (split or {}).get(o.get("id"), 1)
            if n > 1 and u % n == 0:
                u //= n
            out.append((oid, u))
    return out


def apply_to(d: dict, ctx: Ctx, option_id: int, units: int = 1) -> dict:
    """가격 책정 화면 옵션·묶음 dict 의 운임을 이 예측으로 바꾼다 (2026-11-27 — 마켓 판매가는 이 운임으로 매겼는데
    화면은 예전 추정(용량+박스 500g)을 써서 차익이 다르게 보이던 것). 예전 값은 legacy_* 로 남긴다."""
    from decimal import Decimal
    from services.product.serializers import money_cny
    e = estimate(ctx, [(option_id, units)])
    return {
        **d,
        "legacy_shipping_cny": d.get("shipping_cny"), "legacy_weight_g": d.get("weight_g"),
        "shipping_cny": money_cny(Decimal(str(e["fee_cny"]))),
        "weight_g": e["actual_g"], "dim_weight_g": e["dim_g"], "billable_kg": format(e["billable_kg"], ".1f"),
        "box_assumed": False, "over_limit": e["over_limit"],
        "weight_source": "measured" if e["basis"] == ["measured"] else ("product" if e["basis"] == ["product"] else "estimate"),
        "shipping_rate": e["rate"], "shipping_basis": e["basis"],
        "shipping_note": "; ".join(l["note"] for l in e["items"]),
    }
