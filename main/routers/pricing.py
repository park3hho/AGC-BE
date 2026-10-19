import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from schemas.pricing import PricingSave
from services.product.pricing_service import PricingService, parse_platform

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["Pricing"])


@router.get("/{product_id}/pricing")
async def get_pricing(product_id: int, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(**await PricingService.get(product_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"가격 책정 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.put("/{product_id}/pricing/{platform}")
async def save_pricing(
    product_id: int, platform: str, body: PricingSave, auth=Depends(require_feature(Feature.RESEARCH))
):
    try:
        pf = parse_platform(platform)     # 알 수 없는 판매처는 422 가 아니라 404
        return success(pricing=await PricingService.save(product_id, pf, body))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"가격 책정 저장 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
