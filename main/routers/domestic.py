import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_feature
from core.domestic_config import DOMESTIC_STATUS
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.domestic import DomesticCreate, DomesticUpdate
from services.order.domestic_service import DomesticService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/domestic-shipments", tags=["DomesticShipment"])

# 국내 배송 기록 — 주문과 같은 order 권한. 바꿀 때마다 연결된 고객 주문의 추적 기록(OrderEvent domestic_*)에 남는다 (2026-11-03).


def _fail(what: str, e: Exception, domestic_id=None):
    where = f" domestic_id={domestic_id}" if domestic_id is not None else ""
    logger.error(f"국내 배송 기록 {what} 실패:{where} {type(e).__name__}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_domestic(
    order_id: Optional[int] = Query(default=None, ge=1),
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=500),
    auth=Depends(require_feature(Feature.ORDER)),
):
    if status and status not in DOMESTIC_STATUS:
        raise HTTPException(status_code=400, detail="국내 배송 상태가 올바르지 않습니다.")
    try:
        return success(items=await DomesticService.list(order_id, status, q, limit), status=DOMESTIC_STATUS)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록 조회", e)


@router.post("")
async def create_domestic(body: DomesticCreate, auth=Depends(require_feature(Feature.ORDER))):
    try:
        j = await DomesticService.create(body, auth)
        logger.info(f"국내 배송 기록 추가: domestic_id={j['id']} order_id={j['order']['id']} by={auth['user_id']}")
        return success(domestic=j)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("추가", e)


@router.get("/{domestic_id}")
async def get_domestic(domestic_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(domestic=await DomesticService.get(domestic_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("조회", e, domestic_id)


@router.patch("/{domestic_id}")
async def update_domestic(domestic_id: int, body: DomesticUpdate, auth=Depends(require_feature(Feature.ORDER))):
    try:
        j = await DomesticService.update(domestic_id, body, auth)
        logger.info(f"국내 배송 기록 수정: domestic_id={domestic_id} fields={sorted(body.model_fields_set)} by={auth['user_id']}")
        return success(domestic=j)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("수정", e, domestic_id)


@router.delete("/{domestic_id}")
async def delete_domestic(domestic_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        await DomesticService.delete(domestic_id, auth)
        logger.info(f"국내 배송 기록 삭제: domestic_id={domestic_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e, domestic_id)


@router.post("/{domestic_id}/refresh")
async def refresh_domestic_one(domestic_id: int, auth=Depends(require_feature(Feature.ORDER))):
    """지금 마켓 발송처리 · 배송 조회를 다시 본다 (30분 기다리지 않고)."""
    try:
        return success(domestic=await DomesticService.refresh(domestic_id, auth))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("배송 조회", e, domestic_id)