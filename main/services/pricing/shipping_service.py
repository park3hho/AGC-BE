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
    SHIPPING_CATEGORY_LABEL,
    SHIPPING_FIRST_CNY,
    SHIPPING_FIRST_KG,
    SHIPPING_MAX_KG,
    SHIPPING_SERVICE_LABEL,
    SHIPPING_STEP_CNY,
    SHIPPING_STEP_KG,
)
from models.product.price_survey import PriceSurveyOption
from services.pricing.exchange_rate_service import ExchangeRateService
from services.product.price_survey_service import alive_surveys
from services.product.product_service import alive_products
from services.product.serializers import money_cny, product_dict
from utils.volume import parse_volume_ml, scale_pack


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


def option_shipping(option1: str, option2: Optional[str]) -> dict:
    """옵션 1개의 배송비. 용량을 못 읽으면 값이 전부 null (배송비 계산 불가)."""
    volume = parse_volume_ml(option1, option2)
    if volume is None:
        return {"volume_ml": None, "weight_g": None, "billable_kg": None, "shipping_cny": None, "over_limit": False}
    weight = volume * G_PER_ML + BOX_WEIGHT_G
    billable = billable_kg(weight)
    return {
        "volume_ml": volume,
        "weight_g": weight,
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


def option_dict(o: PriceSurveyOption) -> dict:
    """가격 책정 · 배송비 화면 공통 옵션 모양 (옵션 + 배송비)."""
    return {
        "id": o.id, "option1": o.option1, "option2": o.option2,
        "price_cny": money_cny(o.price_cny), "photo_url": o.photo_url,
        **option_shipping(o.option1, o.option2),
    }


# ── 묶음 판매 (core/shipping_config 묶음 판매) ─────────────────────────────────

def bundle_key(option_id: int, n: int) -> str:
    """판매 옵션 키 — 묶음 1 은 조사 옵션 id 그대로, 2 이상은 "66x2". 쿠팡 SKU 끝에도 같은 꼴로 붙인다."""
    return str(option_id) if n == 1 else f"{option_id}x{n}"


def bundle_option_dict(o: PriceSurveyOption, n: int, suggested: bool = False) -> dict:
    """조사 옵션 N개 묶음 = 판매 옵션 1개. 원가 N배 · 용량 N배 + 박스 1개로 운임을 다시 계산한다.
    market_option2 = 마켓에 올릴 용량·입수 ("330ml×48캔"), pack_note = "24캔×2" 같은 설명."""
    volume1 = parse_volume_ml(o.option1, o.option2)
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
    if volume1 is None:
        return {**base, "volume_ml": None, "weight_g": None, "billable_kg": None, "shipping_cny": None,
                "over_limit": False}
    volume = volume1 * n
    weight = volume * G_PER_ML + BOX_WEIGHT_G
    billable = billable_kg(weight)
    return {
        **base, "volume_ml": volume, "weight_g": weight, "billable_kg": _kg(billable),
        "shipping_cny": money_cny(shipping_cny_for(billable)), "over_limit": billable > SHIPPING_MAX_KG,
    }


def suggested_bundle_qty(o: PriceSurveyOption) -> Optional[int]:
    """이 옵션을 10kg 이상으로 만드는 가장 작은 묶음 수. 이미 10kg 이상 · 용량 모름 · 한도(30kg·면세)를 넘으면 None."""
    volume = parse_volume_ml(o.option1, o.option2)
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


def bundle_suggestions(options: list[PriceSurveyOption]) -> list[tuple[PriceSurveyOption, int]]:
    """제품의 가장 무거운 옵션(같은 용량이면 맛별로 전부)도 10kg 미만이면 그 옵션들의 묶음을 제안한다."""
    vols = {o.id: parse_volume_ml(o.option1, o.option2) for o in options}
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

        options_by_survey: dict[int, list] = {s.id: [] for s in base_by_product.values()}
        if options_by_survey:
            for o in await PriceSurveyOption.filter(survey_id__in=list(options_by_survey)).order_by("id"):
                options_by_survey[o.survey_id].append(o)

        items = []
        for p in products:
            s = base_by_product.get(p.id)
            items.append({
                "product": product_dict(p),
                "survey": {"id": s.id, "code": s.code, "survey_date": s.survey_date.isoformat()} if s else None,
                "options": [option_dict(o) for o in options_by_survey.get(s.id, [])] if s else [],
            })
        return {
            "fx": await ExchangeRateService.current(),
            "rule": shipping_rule(),
            "items": items, "total": total, "page": page, "size": size,
        }
