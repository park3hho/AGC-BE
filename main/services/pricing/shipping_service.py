"""배송비 — 옵션 이름의 용량(ml)으로 무게를 잡고 집운 식품 요금표로 계산한다 (core/shipping_config.py).

배송비는 위안으로 계산해 내려준다. 원화는 FE 가 현재 환율을 곱한다 (가격 책정과 같은 환율).
"""

from decimal import ROUND_CEILING, Decimal
from typing import Optional

from core.shipping_config import (
    BOX_WEIGHT_G,
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
from utils.volume import parse_volume_ml


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


def option_dict(o: PriceSurveyOption) -> dict:
    """가격 책정 · 배송비 화면 공통 옵션 모양 (옵션 + 배송비)."""
    return {
        "id": o.id, "option1": o.option1, "option2": o.option2,
        "price_cny": money_cny(o.price_cny), "photo_url": o.photo_url,
        **option_shipping(o.option1, o.option2),
    }


class ShippingService:
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
