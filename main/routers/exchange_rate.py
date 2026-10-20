import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from schemas.pricing import ExchangeRateSave
from services.pricing.exchange_rate_service import ExchangeRateService
from services.pricing.fx_fetch import FxFetchError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/exchange-rate", tags=["ExchangeRate"])


@router.get("")
async def get_exchange_rate(auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(**await ExchangeRateService.overview())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"환율 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.put("")
async def save_exchange_rate(body: ExchangeRateSave, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        current = await ExchangeRateService.set_manual(body.cny_krw)
        logger.info(f"환율 직접 입력: {current['cny_krw']} (user_id={auth['user_id']})")
        return success(current=current)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"환율 저장 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.post("/refresh")
async def refresh_exchange_rate(auth=Depends(require_feature(Feature.RESEARCH))):
    """지금 받아오기 — 오늘 직접 입력한 값이 있어도 받은 값으로 바꾼다."""
    try:
        result = await ExchangeRateService.refresh(force=True)
        logger.info(f"환율 지금 받기: {result['fetched']} (user_id={auth['user_id']})")
        return success(**await ExchangeRateService.overview(), fetched=result["fetched"])
    except FxFetchError:
        raise HTTPException(status_code=502, detail="환율을 받아오지 못했어요. 잠시 뒤 다시 해 주세요.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"환율 받기 실패: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
