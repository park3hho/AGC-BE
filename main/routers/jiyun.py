import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_feature
from core.jiyun_config import JIYUN_STATUS
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.jiyun import JiyunCreate, JiyunUpdate
from services.order.jiyun_service import JiyunService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jiyun-shipments", tags=["JiyunShipment"])

# 집운 기록 — 주문과 같은 order 권한. 바꿀 때마다 연결된 고객 주문의 추적 기록(OrderEvent jiyun_*)에 남는다.


def _fail(what: str, e: Exception, jiyun_id=None):
    where = f" jiyun_id={jiyun_id}" if jiyun_id is not None else ""
    logger.error(f"집운 기록 {what} 실패:{where} {type(e).__name__}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_jiyun(
    order_id: Optional[int] = Query(default=None, ge=1),
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=60),
    limit: int = Query(default=100, ge=1, le=500),
    auth=Depends(require_feature(Feature.ORDER)),
):
    if status and status not in JIYUN_STATUS:
        raise HTTPException(status_code=400, detail="집운 상태가 올바르지 않습니다.")
    try:
        return success(items=await JiyunService.list(order_id, status, q, limit), status=JIYUN_STATUS)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록 조회", e)


@router.post("")
async def create_jiyun(body: JiyunCreate, auth=Depends(require_feature(Feature.ORDER))):
    try:
        j = await JiyunService.create(body, auth)
        logger.info(f"집운 기록 추가: jiyun_id={j['id']} order_id={j['order']['id']} by={auth['user_id']}")
        return success(jiyun=j)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("추가", e)


@router.get("/{jiyun_id}")
async def get_jiyun(jiyun_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(jiyun=await JiyunService.get(jiyun_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("조회", e, jiyun_id)


@router.patch("/{jiyun_id}")
async def update_jiyun(jiyun_id: int, body: JiyunUpdate, auth=Depends(require_feature(Feature.ORDER))):
    try:
        j = await JiyunService.update(jiyun_id, body, auth)
        logger.info(f"집운 기록 수정: jiyun_id={jiyun_id} fields={sorted(body.model_fields_set)} by={auth['user_id']}")
        return success(jiyun=j)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("수정", e, jiyun_id)


@router.delete("/{jiyun_id}")
async def delete_jiyun(jiyun_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        await JiyunService.delete(jiyun_id, auth)
        logger.info(f"집운 기록 삭제: jiyun_id={jiyun_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e, jiyun_id)
