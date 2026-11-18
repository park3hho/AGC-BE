import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from services import shop_analytics

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shop-analytics", tags=["ShopAnalytics"])

# 자사몰 분석 (2026-11-15) — 방문자 · 유입 경로 · 많이 본 상품 · 구매 단계. 주문 권한 (개인정보 없음)


@router.get("")
async def shop_analytics_summary(date_from: Optional[date] = Query(default=None, alias="from"),
                                 date_to: Optional[date] = Query(default=None, alias="to"),
                                 all: bool = Query(default=False),   # true = 해외 접속 · 우리 계정까지 전부 (기본은 국내 손님만)
                                 auth=Depends(require_feature(Feature.ORDER))):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="시작일이 종료일보다 늦어요.")
    if date_from and date_to and (date_to - date_from).days > 400:
        raise HTTPException(status_code=400, detail="기간은 400일까지예요.")
    try:
        return success(**await shop_analytics.summary(date_from, date_to, all))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"자사몰 분석 실패: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/digest")
async def shop_analytics_digest(hours: int = Query(default=6, ge=1, le=168), auth=Depends(require_feature(Feature.ORDER))):
    """최근 N시간 유입 요약 — 진짜 손님 · 유입 경로 · 구매 단계 · 뺀 방문(해외 · 몰아치기 봇 · 우리 계정) · 서버 무효 요청 (2026-11-18).
    6시간마다 도는 점검 루틴은 같은 내용을 scripts/shop_digest.py 로 읽는다."""
    try:
        return success(**await shop_analytics.digest(hours))
    except Exception as e:
        logger.error(f"자사몰 유입 요약 실패: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")