"""모델 → 응답 dict. 응답 모양은 docs/api-contract.md 기준."""

from decimal import Decimal
from typing import Optional


def money_cny(v) -> Optional[str]:
    """위안 가격은 소수 오차를 막으려고 문자열 "39.90" 으로 내려준다."""
    if v is None:
        return None
    return format(Decimal(str(v)), ".2f")


SPEC_KEYS = ("unit_amount", "unit", "unit_count", "count_word", "pack_count", "total_count",
             "spec_note", "spec_checked", "spec_source")


def option_spec_dict(o) -> dict:
    """옵션 규격 구조 칸 (2026-11-22, utils/option_spec). unit_amount 는 문자열 ("3" · "2.8") — 소수 오차 방지."""
    d = {k: getattr(o, k, None) for k in SPEC_KEYS}
    if d["unit_amount"] is not None:
        d["unit_amount"] = format(Decimal(str(d["unit_amount"])).normalize(), "f")
    d["spec_checked"] = bool(d["spec_checked"])
    return d


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
        "label_images": p.label_images or [],
        "nutrition": p.nutrition,
        "category": p.category,
        "subcategory": p.subcategory,
        "tea_form": p.tea_form,
        "shipping_mode": p.shipping_mode,                   # included 배송비 포함형 · separate 배송비 별도형 · null 미분류 (2026-11-20)
        "shipping_mode_source": p.shipping_mode_source,     # auto · manual
        "unit_weight_g": p.unit_weight_g, "unit_count": p.unit_count, "shipping_mode_note": p.shipping_mode_note,
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
                **option_spec_dict(o),
            }
            for o in options
        ],
    }
