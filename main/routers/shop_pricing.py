"""가격 책정 › 자사몰 판매 — 자사몰 판매가 계산 (계산 · 표시만, 2026-11-27)."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from services.pricing.shop_calc import calc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shop-pricing", tags=["ShopPricing"])


@router.get("")
async def shop_pricing(auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(**await calc())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"자사몰 판매가 계산 실패: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
