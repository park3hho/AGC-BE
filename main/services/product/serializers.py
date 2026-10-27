"""모델 → 응답 dict. 응답 모양은 docs/api-contract.md 기준."""

from decimal import Decimal
from typing import Optional


def money_cny(v) -> Optional[str]:
    """위안 가격은 소수 오차를 막으려고 문자열 "39.90" 으로 내려준다."""
    if v is None:
        return None
    return format(Decimal(str(v)), ".2f")


def product_dict(p) -> dict:
    return {
        "id": p.id,
        "code": p.code,
        "photo_url": p.photo_url,
        "photo_hover_url": p.photo_hover_url,
        "photos": p.photos or [],
        "title_cn": p.title_cn,
        "title_ko": p.title_ko,
        "manufacturer": p.manufacturer,
        "ingredients": p.ingredients,
        "allergens": p.allergens,
        "shelf_life": p.shelf_life,
        "storage": p.storage,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def _survey_base(s) -> dict:
    return {
        "id": s.id,
        "code": s.code,
        "survey_date": s.survey_date.isoformat(),
        "product": {"id": s.product.id, "code": s.product.code, "title_ko": s.product.title_ko},
        "photo_url": s.photo_url,
        "taobao_url": s.taobao_url,
        "coupang_min_price": s.coupang_min_price,
        "coupang_url": s.coupang_url,
        "naver_min_price": s.naver_min_price,
        "naver_url": s.naver_url,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
    }


def survey_summary_dict(s) -> dict:
    """목록용 — s 에 option_count / min_price / max_price annotate 가 붙어 있어야 한다."""
    return {
        **_survey_base(s),
        "option_count": s.option_count,
        "min_price_cny": money_cny(s.min_price),
        "max_price_cny": money_cny(s.max_price),
    }


def survey_detail_dict(s, options) -> dict:
    return {
        **_survey_base(s),
        "option_count": len(options),
        "options": [
            {
                "id": o.id, "option1": o.option1, "option2": o.option2,
                "price_cny": money_cny(o.price_cny), "photo_url": o.photo_url, "barcode": o.barcode,
            }
            for o in options
        ],
    }
