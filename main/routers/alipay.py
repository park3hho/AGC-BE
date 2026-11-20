"""알리페이(즈푸바오) 잔액 장부 — 충전 환율 선입선출로 잔액 결제 원화 계산 (2026-11-20). order 권한 · API 키 허용(개인정보 없음)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from core.response_utils import success, success_only
from routers.ops import require_ops
from schemas.alipay import SpendIn, TopupIn, TopupPatch
from services.order import alipay_ledger as L

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alipay-balance", tags=["AlipayBalance"])


def _fail(what: str, e: Exception):
    logger.error(f"알리페이 장부 {what} 실패: {type(e).__name__}: {e}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def get_ledger(limit: int = Query(default=200, ge=1, le=1000), auth=Depends(require_ops)):
    try:
        return success(**await L.ledger(limit))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("조회", e)


@router.post("/topups")
async def add_topup(body: TopupIn, auth=Depends(require_ops)):
    try:
        return success(**await L.add_topup(body.model_dump()))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("충전 기록", e)


@router.patch("/topups/{tid}")
async def patch_topup(tid: int, body: TopupPatch, auth=Depends(require_ops)):
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
    try:
        return success(**await L.patch_topup(tid, data))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("충전 수정", e)


@router.delete("/topups/{tid}")
async def delete_topup(tid: int, auth=Depends(require_ops)):
    try:
        await L.delete_topup(tid)
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("충전 삭제", e)


@router.post("/spends")
async def add_spend(body: SpendIn, auth=Depends(require_ops)):
    try:
        return success(**await L.add_spend(body.model_dump()))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("결제 기록", e)


@router.delete("/spends/{sid}")
async def delete_spend(sid: int, auth=Depends(require_ops)):
    try:
        await L.delete_spend(sid)
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("결제 삭제", e)


@router.post("/recompute")
async def recompute(auth=Depends(require_ops)):
    try:
        r = await L.recompute(True)
        return success(**{k: v for k, v in r.items() if k != "lots"}, lots=r.get("lots"))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("다시 계산", e)
