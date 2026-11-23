"""배송비 — 옵션 이름의 용량(ml)으로 무게를 잡고 집운 식품 요금표로 계산한다 (core/shipping_config.py).

배송비는 위안으로 계산해 내려준다. 원화는 FE 가 현재 환율을 곱한다 (가격 책정과 같은 환율).
"""

from decimal import ROUND_CEILING, Decimal
from typing import Optional

from core.shipping_config import (
    BOX_WEIGHT_G,
    BUNDLE_MAX_QTY,
    BUNDLE_TARGET_KG,
    CNY_PER_USD,
    DUTY_FREE_USD,
    G_PER_ML,
    MIN_BOX_CM,
    SHIPPING_CATEGORY_LABEL,
    SHIPPING_FIRST_CNY,
    SHIPPING_FIRST_KG,
    SHIPPING_MAX_KG,
    SHIPPING_SERVICE_LABEL,
    SHIPPING_STEP_CNY,
    SHIPPING_STEP_KG,
    SHIPPING_BILLABLE_RULE,
    SHIPPING_ETA,
    SHIPPING_NOTES,
    SHIPPING_RATES,
    SHIPPING_ROUNDING,
    SHIPPING_SIZE_LIMITS,
    SHIPPING_SOURCE_CHECKED,
    SHIPPING_SOURCE_URL,
    SHIPPING_TAX_NOTE,
    TEA_BOX_CM,
    VOLUMETRIC_DIVISOR,
    VOLUMETRIC_SOURCE_URL,
)
from models.product.price_survey import ProductOption
from services.pricing.exchange_rate_service import ExchangeRateService
from services.product.price_survey_service import alive_surveys
from services.product.product_service import alive_products
from services.product.serializers import money_cny, product_dict
from utils.option_spec import spec_volume_ml
from utils.volume import parse_box_cm, parse_box_per, parse_volume_ml, scale_pack


def option_volume_ml(option1: Optional[str], option2: Optional[str], spec=None) -> Optional[int]:
    """옵션 총 용량(ml, 1g = 1ml) — 규격 구조 칸(unit_amount × total_count, utils/option_spec)을 먼저 쓰고,
    비어 있으면 예전 글자 해석(parse_volume_ml). spec = ProductOption 같은 구조 칸을 가진 객체·dict (2026-11-22)."""
    v = spec_volume_ml(spec)
    return v if v is not None else parse_volume_ml(option1, option2)


def _kg(v: Decimal) -> str:
    return format(v, ".1f")


def billable_kg(weight_g: int) -> Decimal:
    """계산 무게 — 첫 1kg 미만은 1kg, 넘는 무게는 0.5kg 단위 올림."""
    kg = Decimal(weight_g) / Decimal(1000)
    if kg <= SHIPPING_FIRST_KG:
        return SHIPPING_FIRST_KG
    steps = ((kg - SHIPPING_FIRST_KG) / SHIPPING_STEP_KG).to_integral_value(rounding=ROUND_CEILING)
    return SHIPPING_FIRST_KG + steps * SHIPPING_STEP_KG


def shipping_cny_for(billable: Decimal) -> Decimal:
    steps = (billable - SHIPPING_FIRST_KG) / SHIPPING_STEP_KG
    return SHIPPING_FIRST_CNY + steps * SHIPPING_STEP_CNY


def dim_weight_g(n: int = 1) -> int:
    """차(tea) 상자 N개의 부피 무게(g) — core/shipping_config 부피 무게."""
    a, b, c = TEA_BOX_CM
    return int(Decimal(a * b * c * n) * 1000 / VOLUMETRIC_DIVISOR)


def min_box_dim_g(n: int = 1) -> int:
    """용량을 못 읽은 상품의 최소 상자(세 변 합 50cm) N개 부피 무게(g)."""
    a, b, c = MIN_BOX_CM
    return int(Decimal(a * b * c * n) * 1000 / VOLUMETRIC_DIVISOR)


def box_dim_weight_g(box_cm: tuple, n: int = 1, per: int = 1) -> int:
    """옵션에 적힌 상자(가로×세로×높이 cm)의 부피 무게(g)를 조사 옵션 n개 분량으로.
    per = 그 상자가 조사 옵션 몇 개 분량인지 ("3박스 묶음 시 상자 약 …" → 3)."""
    a, b, c = box_cm
    return int(Decimal(str(a)) * Decimal(str(b)) * Decimal(str(c)) * n * 1000 / VOLUMETRIC_DIVISOR / max(1, per))


def _weights(volume: Optional[int], n: int, category: str,
             box_cm: Optional[tuple] = None, box_per: int = 1) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """(실제 무게, 부피 무게, 계산에 쓸 무게) g. 음료는 실제 무게만. 차는 둘 중 큰 값 — 용량을 못 읽어도 부피 무게로 잡는다.
    음료도 용량을 못 읽으면 최소 상자(세 변 합 50cm, core/shipping_config.MIN_BOX_CM) 부피 무게로 잡는다 (2026-10-30).
    옵션 이름에 상자 크기("상자 약 50×30×30cm")가 있으면 그 부피 무게와 실제 무게 중 큰 값 — 과자처럼 가볍고 큰 상품 (2026-11-17 사용자).
    묶음 N개는 상자도 N개로 본다. "3박스 묶음 시 상자 약 …" 처럼 상자가 여러 개 분량이면 그만큼 나눈다 (box_per)."""
    actual = volume * n * G_PER_ML + BOX_WEIGHT_G if volume is not None else None
    if box_cm:
        dim = box_dim_weight_g(box_cm, n, box_per)
        return actual, dim, max(actual or 0, dim)
    if category != "tea" and actual is None:
        dim = min_box_dim_g(n)
        return None, dim, dim
    if category != "tea":
        return actual, None, actual
    dim = dim_weight_g(n)
    return actual, dim, max(actual or 0, dim)


def option_shipping(option1: str, option2: Optional[str], category: str = "beverage", spec=None) -> dict:
    """옵션 1개의 배송비. 용량을 못 읽으면 값이 전부 null (배송비 계산 불가) — 차는 부피 무게로 계산한다.
    spec = 구조 칸을 가진 옵션(ProductOption) — 있으면 용량은 구조 칸 우선."""
    volume = option_volume_ml(option1, option2, spec)
    box_text = option2 if parse_box_cm(option2) else option1
    actual, dim, weight = _weights(volume, 1, category, parse_box_cm(box_text), parse_box_per(box_text))
    if weight is None:
        return {"volume_ml": None, "weight_g": None, "dim_weight_g": None, "billable_kg": None,
                "shipping_cny": None, "over_limit": False}
    billable = billable_kg(weight)
    return {
        "box_assumed": volume is None and category != "tea" and dim is not None and not (parse_box_cm(option2) or parse_box_cm(option1)),   # 용량을 못 읽어 최소 상자(세 변 합 50cm)로 계산함
        "volume_ml": volume,
        "weight_g": actual,
        "dim_weight_g": dim,          # 부피 무게 (차 · 상자 크기를 적은 옵션) — 계산 무게는 실제·부피 중 큰 값
        "billable_kg": _kg(billable),
        "shipping_cny": money_cny(shipping_cny_for(billable)),
        "over_limit": billable > SHIPPING_MAX_KG,
    }


def shipping_rule() -> dict:
    """화면에 보여줄 요금 규칙."""
    return {
        "service": SHIPPING_SERVICE_LABEL,
        "category": SHIPPING_CATEGORY_LABEL,
        "first_kg": _kg(SHIPPING_FIRST_KG),
        "first_cny": money_cny(SHIPPING_FIRST_CNY),
        "step_kg": _kg(SHIPPING_STEP_KG),
        "step_cny": money_cny(SHIPPING_STEP_CNY),
        "max_kg": _kg(SHIPPING_MAX_KG),
        "box_weight_g": BOX_WEIGHT_G,
        # 타오바오 공식 집운 안내 (화면 표시용 — 계산은 위 식품 요율)
        "eta": SHIPPING_ETA,
        "rates": SHIPPING_RATES,                 # [{name, cn, range, price, applied}] applied = AGC 계산에 쓰는 요율
        "billable_rule": SHIPPING_BILLABLE_RULE,
        "rounding": SHIPPING_ROUNDING,
        "size_limits": SHIPPING_SIZE_LIMITS,
        "tax_note": SHIPPING_TAX_NOTE,
        "notes": SHIPPING_NOTES,
        "volumetric": {                          # 부피 무게 — 차(tea) 제품만 반영
            "divisor": VOLUMETRIC_DIVISOR,
            "applies_to": "tea · 옵션에 상자 크기(cm)를 적은 상품",
            "box_cm": list(TEA_BOX_CM),
            "box_weight_g": dim_weight_g(1),
            "source_url": VOLUMETRIC_SOURCE_URL,
            "source_note": "나누는 값은 공식 집운 안내에 없음 — 타오바오 국제물류 안내 예시(6000)",
        },
        "source_url": SHIPPING_SOURCE_URL,
        "source_checked": SHIPPING_SOURCE_CHECKED,
    }


def shipping_brackets() -> list[dict]:
    """무게 구간별 요금표 — 첫 무게부터 소형 한도까지 0.5kg 단위.
    max_volume_ml = 이 구간에 들어가는 최대 용량 (무게 − 박스, 1ml = 1g)."""
    rows = []
    kg = SHIPPING_FIRST_KG
    while kg <= SHIPPING_MAX_KG:
        max_weight_g = int(kg * 1000)
        rows.append({
            "billable_kg": _kg(kg),
            "max_volume_ml": max(0, (max_weight_g - BOX_WEIGHT_G) // G_PER_ML),
            "shipping_cny": money_cny(shipping_cny_for(kg)),
        })
        kg += SHIPPING_STEP_KG
    return rows


def apply_measured(d: dict, measured: Optional[dict]) -> dict:
    """실측 평균(services/order/measure_service.measure_averages)이 있으면 배송비를 실측으로 다시 계산한다 (2026-11-18).
    계산 무게 = 실측 무게와 실측 상자 부피 무게(가로×세로×높이 / VOLUMETRIC_DIVISOR) 중 큰 값. 추정값은 estimate_* 로 남긴다."""
    if not measured or measured.get("weight_kg") is None:
        return {**d, "weight_source": "estimate"}
    actual = int(round(measured["weight_kg"] * 1000))
    est = d.get("weight_g")
    # 추정의 60% 미만 · 160% 초과면 상자를 나눠 보낸 주문(일부만 잰) 등 잘못 붙은 실측일 수 있어 쓰지 않고 표시만 한다
    if est and not (0.6 * est <= actual <= 1.6 * est):
        return {**d, "weight_source": "estimate", "measured": measured, "measured_outlier": True}
    dim = None
    if measured.get("length_cm") and measured.get("width_cm") and measured.get("height_cm"):
        dim = int(round(measured["length_cm"] * measured["width_cm"] * measured["height_cm"] / VOLUMETRIC_DIVISOR * 1000))
    billable = billable_kg(max(actual, dim or 0))
    return {
        **d, "weight_source": "measured", "measured": measured,
        "estimate_weight_g": d.get("weight_g"), "estimate_shipping_cny": d.get("shipping_cny"),
        "weight_g": actual, "dim_weight_g": dim, "box_assumed": False,
        "billable_kg": _kg(billable), "shipping_cny": money_cny(shipping_cny_for(billable)),
        "over_limit": billable > SHIPPING_MAX_KG,
    }


def option_dict(o: ProductOption, category: str = "beverage", measured: Optional[dict] = None) -> dict:
    """가격 책정 · 배송비 화면 공통 옵션 모양 (옵션 + 배송비). category = 제품 대분류 (차는 부피 무게).
    measured = 이 옵션 1개 상자의 실측 평균 (있으면 배송비는 실측 기준)."""
    return apply_measured({
        "id": o.id, "option1": o.option1, "option2": o.option2,
        "price_cny": money_cny(o.price_cny), "photo_url": o.photo_url,
        **option_shipping(o.option1, o.option2, category, spec=o),
    }, measured)


# ── 묶음 판매 (core/shipping_config 묶음 판매) ─────────────────────────────────

def bundle_key(option_id: int, n: int) -> str:
    """판매 옵션 키 — 묶음 1 은 조사 옵션 id 그대로, 2 이상은 "66x2". 쿠팡 SKU 끝에도 같은 꼴로 붙인다."""
    return str(option_id) if n == 1 else f"{option_id}x{n}"


def bundle_option_dict(o: ProductOption, n: int, suggested: bool = False, category: str = "beverage") -> dict:
    """조사 옵션 N개 묶음 = 판매 옵션 1개. 원가 N배 · 용량 N배 + 박스 1개로 운임을 다시 계산한다.
    market_option2 = 마켓에 올릴 용량·입수 ("330ml×48캔"), pack_note = "24캔×2" 같은 설명."""
    volume1 = option_volume_ml(o.option1, o.option2, o)
    price = Decimal(str(o.price_cny)) * n
    base = {
        "key": bundle_key(o.id, n), "option_id": o.id, "bundle_qty": n, "suggested": suggested,
        "option1": o.option1, "option2": o.option2, "price_cny": money_cny(price), "photo_url": o.photo_url,
    }
    # 마켓에 올릴 이름 — 용량·입수가 있는 쪽의 개수를 N배 (없으면 "×N" 을 붙인다)
    s2, s1 = scale_pack(o.option2, n), None if o.option2 and scale_pack(o.option2, n) else scale_pack(o.option1, n)
    if s2:
        m1, m2, count, unit = o.option1, s2["text"], s2["count"], s2["unit_text"]
    elif s1:
        m1, m2, count, unit = s1["text"], o.option2 or "", s1["count"], s1["unit_text"]
    else:
        m1, m2, count, unit = (f"{o.option1} ×{n}" if n > 1 else o.option1), o.option2 or "", None, "1개"
    base.update(market_option1=m1, market_option2=m2, total_count=count,
                pack_note=f"{unit}×{n}" if n > 1 else None)   # "24캔×2"
    base["over_duty_free"] = price / CNY_PER_USD > DUTY_FREE_USD
    box_text = o.option2 if parse_box_cm(o.option2) else o.option1
    box = parse_box_cm(box_text)
    actual, dim, weight = _weights(volume1, n, category, box, parse_box_per(box_text))
    if weight is None:
        return {**base, "volume_ml": None, "weight_g": None, "dim_weight_g": None, "billable_kg": None,
                "shipping_cny": None, "over_limit": False}
    billable = billable_kg(weight)
    return {
        **base, "box_assumed": volume1 is None and category != "tea" and not box,
        "volume_ml": volume1 * n if volume1 is not None else None, "weight_g": actual,
        "dim_weight_g": dim, "billable_kg": _kg(billable),
        "shipping_cny": money_cny(shipping_cny_for(billable)), "over_limit": billable > SHIPPING_MAX_KG,
    }


def suggested_bundle_qty(o: ProductOption) -> Optional[int]:
    """이 옵션을 10kg 이상으로 만드는 가장 작은 묶음 수. 이미 10kg 이상 · 용량 모름 · 한도(30kg·면세)를 넘으면 None."""
    volume = option_volume_ml(o.option1, o.option2, o)
    if volume is None:
        return None
    target_g = int(BUNDLE_TARGET_KG * 1000)
    if volume * G_PER_ML + BOX_WEIGHT_G >= target_g:
        return None
    for n in range(2, BUNDLE_MAX_QTY + 1):
        if volume * n * G_PER_ML + BOX_WEIGHT_G >= target_g:
            d = bundle_option_dict(o, n)
            return None if d["over_limit"] or d["over_duty_free"] else n
    return None


def bundle_suggestions(options: list[ProductOption]) -> list[tuple[ProductOption, int]]:
    """제품의 가장 무거운 옵션(같은 용량이면 맛별로 전부)도 10kg 미만이면 그 옵션들의 묶음을 제안한다."""
    vols = {o.id: option_volume_ml(o.option1, o.option2, o) for o in options}
    known = [v for v in vols.values() if v]
    if not known:
        return []
    heaviest = max(known)
    out = []
    for o in options:
        if vols[o.id] == heaviest:
            n = suggested_bundle_qty(o)
            if n:
                out.append((o, n))
    return out


class ShippingService:
    @staticmethod
    async def rule() -> dict:
        """요금 규칙 + 무게 구간별 요금표 + 현재 환율 (배송비 화면)."""
        return {
            "fx": await ExchangeRateService.current(),
            "rule": shipping_rule(),
            "brackets": shipping_brackets(),
        }

    @staticmethod
    async def list(page: int, size: int) -> dict:
        """제품별 기준 조사(최신) 옵션의 배송비."""
        qs = alive_products()
        total = await qs.count()
        products = await qs.order_by("-created_at", "-id").offset((page - 1) * size).limit(size)

        # 제품마다 기준 조사 = 조사일 최근 → id 큰 순 1건 (가격 책정과 같은 규칙)
        base_by_product = {}
        if products:
            surveys = await alive_surveys().filter(product_id__in=[p.id for p in products]).order_by(
                "product_id", "-survey_date", "-id"
            )
            for s in surveys:
                base_by_product.setdefault(s.product_id, s)

        # 옵션 = 제품 옵션 (id 고정, 지운 것 빼고). 살아 있는 조사가 없는 제품은 예전처럼 빈 목록
        options_by_product: dict[int, list] = {pid: [] for pid in base_by_product}
        if options_by_product:
            for o in await ProductOption.filter(product_id__in=list(options_by_product), deleted_at=None).order_by("sort", "id"):
                options_by_product[o.product_id].append(o)

        items = []
        for p in products:
            s = base_by_product.get(p.id)
            items.append({
                "product": product_dict(p),
                "survey": {"id": s.id, "code": s.code, "survey_date": s.survey_date.isoformat()} if s else None,
                "options": [option_dict(o, p.category) for o in options_by_product.get(p.id, [])] if s else [],
            })
        return {
            "fx": await ExchangeRateService.current(),
            "rule": shipping_rule(),
            "items": items, "total": total, "page": page, "size": size,
        }
