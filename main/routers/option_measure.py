import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from services.order.measure_service import MeasureService, measure_averages

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/option-measures", tags=["OptionMeasure"])

# 옵션별 실측 (2026-11-18) — services/order/measure_service.py. 비공개: 로그인 · 권한 있는 사용자만 (자사몰 API 아님)


class RecordBody(BaseModel):
    order_id: Optional[int] = None
    order_code: Optional[str] = Field(default=None, max_length=30)   # OR-yymmdd-xxxx
    jiyun_no: Optional[str] = Field(default=None, max_length=60)
    weight_kg: Optional[float] = Field(default=None, gt=0, le=60)
    length_cm: Optional[float] = Field(default=None, gt=0, le=300)
    width_cm: Optional[float] = Field(default=None, gt=0, le=300)
    height_cm: Optional[float] = Field(default=None, gt=0, le=300)
    source: str = Field(default="jiyun", max_length=20)
    mixed: Optional[bool] = None
    memo: Optional[str] = Field(default=None, max_length=2000)


def _fail(what: str, e: Exception):
    logger.error(f"실측 {what} 실패: {type(e).__name__} {str(e)[:200]}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_measures(product_id: Optional[int] = Query(default=None), option_id: Optional[int] = Query(default=None),
                        order_id: Optional[int] = Query(default=None), limit: int = Query(default=200),
                        auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(items=await MeasureService.list(product_id, option_id, order_id, limit))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록", e)


@router.get("/averages")
async def averages(option_ids: str = Query(..., max_length=2000), auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        ids = [int(x) for x in option_ids.split(",") if x.strip().isdigit()]
        avg = await measure_averages(ids)
        return success(items=[{"option_id": k[0], "units": k[1], **v} for k, v in sorted(avg.items())])
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("평균", e)


@router.post("")
async def record(body: RecordBody, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(item=await MeasureService.record(**body.model_dump(), user_id=(auth or {}).get("user_id")))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("기록", e)


@router.delete("/{measure_id}")
async def delete(measure_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        await MeasureService.delete(measure_id)
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e)

