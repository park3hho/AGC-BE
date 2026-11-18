import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from services.order.stock_service import StockService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jiyun-stock", tags=["JiyunStock"])

# 집운 가용재고 (2026-11-18) — services/order/stock_service.py


class CreateBody(BaseModel):
    purchase_id: int
    label: Optional[str] = Field(default=None, max_length=200)
    expires_on: Optional[date] = None
    memo: Optional[str] = Field(default=None, max_length=2000)


class UseBody(BaseModel):
    order_id: Optional[int] = None
    order_code: Optional[str] = Field(default=None, max_length=30)   # OR-yymmdd-xxxx — 화면에서 코드로 넣을 때


class PatchBody(BaseModel):
    status: Optional[str] = Field(default=None, max_length=12)    # available · returned · written_off
    label: Optional[str] = Field(default=None, max_length=200)
    expires_on: Optional[date] = None
    memo: Optional[str] = Field(default=None, max_length=2000)


def _fail(what: str, e: Exception):
    logger.error(f"집운 재고 {what} 실패: {type(e).__name__} {str(e)[:200]}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_stock(status: Optional[str] = Query(default="available"), sku: Optional[str] = Query(default=None),
                     auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(items=await StockService.list(status, sku))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록", e)


@router.get("/match")
async def match_stock(order_id: int = Query(...), auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(items=await StockService.match(order_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("맞는 재고 찾기", e)


@router.post("")
async def create_stock(body: CreateBody, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(item=await StockService.create(body.purchase_id, body.label, body.expires_on, body.memo, auth))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("등록", e)


@router.post("/{stock_id}/use")
async def use_stock(stock_id: int, body: UseBody, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(item=await StockService.use(stock_id, body.order_id, auth, body.order_code))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("쓰기", e)


@router.patch("/{stock_id}")
async def patch_stock(stock_id: int, body: PatchBody, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(item=await StockService.patch(stock_id, body.model_dump(exclude_unset=True), auth))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("수정", e)


@router.delete("/{stock_id}")
async def delete_stock(stock_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        await StockService.delete(stock_id, auth)
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e)
