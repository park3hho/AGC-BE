"""고객 주문 → 타오바오에서 살 것 (조사 옵션 × 묶음 수).

마켓 옵션은 판매 옵션이고, 판매 옵션 = 가격 조사 옵션 × 묶음 수 (models/product/pricing.OptionPrice).
찾는 순서:
  1) 판매자 코드(쿠팡 externalVendorSku · 네이버 판매자 상품/옵션 관리코드)가 `PR-…-{옵션 id}[x{묶음 수}]` 이면 그대로
  2) 마켓 등록 기록(MarketListing.items)에서 마켓 옵션 id(쿠팡 vendorItemId)가 같은 줄
  3) 판매자 코드가 제품 코드뿐이면 제품까지만 (옵션은 사람이 고른다)
타오바오에서 살 수량 = 주문 수량 × 묶음 수.
"""

from typing import Optional

from models.order.order import MarketOrder
from models.product.listing import MarketListing
from models.product.price_survey import PriceSurvey, PriceSurveyOption
from models.product.product import Product
from services.product.listing_service import SKU_RE
from services.product.serializers import money_cny


def _parse(code: Optional[str]):
    m = SKU_RE.match((code or "").strip())
    if not m:
        return None
    return m.group(1).upper(), (int(m.group(2)) if m.group(2) else None), (int(m.group(3)) if m.group(3) else 1)


async def order_sourcing(o: MarketOrder) -> Optional[dict]:
    product_code = option_id = None
    bundle, matched_by = 1, None
    for field, code in (("seller_code", o.seller_code), ("market_option_id", o.market_option_id)):
        got = _parse(code)
        if got and got[1]:
            product_code, option_id, bundle = got
            matched_by = "sku"
            break
        if got and not product_code:
            product_code = got[0]
    if option_id is None and o.market_option_id:
        for lst in await MarketListing.filter(platform=o.market, deleted_at=None):
            it = next((i for i in (lst.items or []) if str(i.get("market_item_id") or "") == o.market_option_id), None)
            if it and it.get("option_id"):
                option_id, bundle, matched_by = it["option_id"], int(it.get("bundle_qty") or 1), "listing"
                product_code = None
                break

    opt = await PriceSurveyOption.get_or_none(id=option_id) if option_id else None
    survey = await PriceSurvey.get_or_none(id=opt.survey_id) if opt else None
    if survey:
        product = await Product.get_or_none(id=survey.product_id)
    elif product_code:
        product = await Product.get_or_none(code=product_code, deleted_at=None)
        matched_by = matched_by or "product_code"
    else:
        product = None
    if not product:
        return None
    if product_code and product.code != product_code:   # SKU 의 제품 코드와 옵션의 제품이 다르면 옵션은 믿지 않는다
        opt, survey = None, None
    if not survey:
        survey = (
            await PriceSurvey.filter(product_id=product.id, deleted_at=None).order_by("-survey_date", "-id").first()
        )
    return {
        "product_id": product.id, "product_code": product.code, "product_title": product.title_ko,
        "taobao_url": survey.taobao_url if survey else None,
        "option_id": opt.id if opt else None,
        "option1": opt.option1 if opt else None, "option2": opt.option2 if opt else None,
        "price_cny": money_cny(opt.price_cny) if opt else None,
        "bundle_qty": bundle if opt else None,
        "taobao_qty": (o.quantity or 1) * bundle if opt else None,   # 타오바오에서 살 개수
        "matched_by": matched_by,                                    # sku · listing · product_code
    }
