import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from schemas.pricing import BundleIn, PricingSave
from services.product.pricing_service import BundleService, PricingService, parse_platform

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


@router.post("/{product_id}/pricing/bundles")
async def adopt_bundle(product_id: int, body: BundleIn, auth=Depends(require_feature(Feature.RESEARCH))):
    """묶음을 판매 옵션으로 채택 (판매가는 비워 둔다)."""
    try:
        return success(**await BundleService.adopt(product_id, body.option_id, body.bundle_qty, auth.get("user_id")))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"묶음 채택 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.delete("/{product_id}/pricing/bundles/{option_id}/{bundle_qty}")
async def drop_bundle(product_id: int, option_id: int, bundle_qty: int,
                      auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(**await BundleService.drop(product_id, option_id, bundle_qty))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"묶음 빼기 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")