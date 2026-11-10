import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from services.order.sales_service import SalesService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sales", tags=["Sales"])

# 매출 현황 (2026-11-10) — 기간(KST 주문일) 안 주문의 매출·정산·구매·집운·이익·마진. 주문 권한


@router.get("/summary")
async def sales_summary(date_from: Optional[date] = Query(default=None, alias="from"),
                        date_to: Optional[date] = Query(default=None, alias="to"),
                        auth=Depends(require_feature(Feature.ORDER))):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="시작일이 종료일보다 늦어요.")
    try:
        return success(**await SalesService.summary(date_from, date_to))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"매출 현황 실패: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
