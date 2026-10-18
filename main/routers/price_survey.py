import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_auth, require_feature
from core.permissions import Feature
from core.response_utils import success
from schemas.price_survey import PriceSurveyCreate
from services.product.price_survey_service import PriceSurveyService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/price-surveys", tags=["PriceSurvey"])


@router.post("")
async def create_price_survey(body: PriceSurveyCreate, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(price_survey=await PriceSurveyService.create(body))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"가격 조사 등록 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_price_surveys(
    product_code: str | None = Query(default=None, max_length=50),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    auth=Depends(require_auth),
):
    try:
        code = product_code.strip() if product_code else None
        return success(**await PriceSurveyService.list(code, page, size))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"가격 조사 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/next-code")    # ★ /{survey_id} 보다 먼저 선언해야 한다
async def get_next_survey_code(survey_date: date, auth=Depends(require_auth)):
    try:
        return success(code=await PriceSurveyService.next_code(survey_date))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"다음 조사 코드 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/{survey_id}")
async def get_price_survey(survey_id: int, auth=Depends(require_auth)):
    try:
        return success(price_survey=await PriceSurveyService.get(survey_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"가격 조사 상세 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
