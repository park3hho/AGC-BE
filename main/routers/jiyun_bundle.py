import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from services.order import bundle_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jiyun-bundles", tags=["JiyunBundle"])

# 집운 묶음 PRE_LP… (2026-11-16) — services/order/bundle_service.py


class MoveBody(BaseModel):
    order_id: int
    target: Optional[str] = Field(default=None, max_length=30)   # 묶음 code · 주문 코드 · 없음 = 따로(새 묶음)


def _fail(what: str, e: Exception):
    logger.error(f"집운 묶음 {what} 실패: {type(e).__name__} {str(e)[:200]}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_bundles(status: Optional[str] = Query(default="active"), include_test: bool = Query(default=False),
                       auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(items=await bundle_service.list_bundles(status, include_test))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록", e)


@router.get("/{code}")
async def get_bundle(code: str, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(bundle=await bundle_service.get_bundle(code))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("조회", e)


@router.post("/{code}/confirm")
async def confirm_bundle(code: str, auth=Depends(require_feature(Feature.ORDER))):
    """묶음 확정 — 더 합류하지 않고 결제 대기 (open → confirmed)."""
    try:
        data = await bundle_service.set_status(code, True)
        logger.info(f"집운 묶음 확정: {code} by={auth['user_id']}")
        return success(bundle=data)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("확정", e)


@router.post("/{code}/reopen")
async def reopen_bundle(code: str, auth=Depends(require_feature(Feature.ORDER))):
    """확정 풀기 — 다시 주문을 받음 (confirmed → open)."""
    try:
        return success(bundle=await bundle_service.set_status(code, False))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("확정 풀기", e)


@router.post("/move")
async def move_order(body: MoveBody, auth=Depends(require_feature(Feature.ORDER))):
    """주문을 다른 묶음으로 / 따로."""
    try:
        from services.order.order_service import OrderService
        data = await OrderService.set_bundle(body.order_id, body.target, auth)
        return success(**data)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("옮기기", e)
