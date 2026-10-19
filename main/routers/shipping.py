import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from services.pricing.shipping_service import ShippingService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shipping-fees", tags=["Shipping"])


@router.get("")
async def list_shipping_fees(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    auth=Depends(require_feature(Feature.RESEARCH)),
):
    try:
        return success(**await ShippingService.list(page, size))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"배송비 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
