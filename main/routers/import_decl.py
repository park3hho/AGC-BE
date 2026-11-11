import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_feature
from core.import_decl_config import DECL_KIND, DECL_STATUS
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.import_decl import DeclCreate, DeclUpdate
from services.order.import_decl_service import ImportDeclService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/import-declarations", tags=["ImportDeclaration"])

# 수입식품 구매대행 수입신고 기록 (2026-11-11) — 주문과 같은 order 권한


def _fail(what: str, e: Exception):
    logger.error(f"수입신고 기록 {what} 실패: {type(e).__name__} {str(e)[:200]}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_decl(
    order_id: Optional[int] = Query(default=None, ge=1),
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=60),
    limit: int = Query(default=200, ge=1, le=500),
    auth=Depends(require_feature(Feature.ORDER)),
):
    try:
        return success(items=await ImportDeclService.list(order_id, status, q, limit), status=DECL_STATUS, kind=DECL_KIND)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록", e)


@router.get("/pending")   # ★ /{decl_id} 보다 먼저
async def pending(auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(items=await ImportDeclService.pending())
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("신고할 것", e)


@router.post("")
async def create_decl(body: DeclCreate, auth=Depends(require_feature(Feature.ORDER))):
    try:
        d = await ImportDeclService.create(body, auth)
        logger.info(f"수입신고 기록 추가: id={d['id']} orders={[o['id'] for o in d['orders']]} by={auth['user_id']}")
        return success(declaration=d)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("추가", e)


@router.get("/{decl_id}")
async def get_decl(decl_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(declaration=await ImportDeclService.get(decl_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("조회", e)


@router.patch("/{decl_id}")
async def update_decl(decl_id: int, body: DeclUpdate, auth=Depends(require_feature(Feature.ORDER))):
    try:
        d = await ImportDeclService.update(decl_id, body, auth)
        logger.info(f"수입신고 기록 수정: id={decl_id} fields={sorted(body.model_fields_set)} by={auth['user_id']}")
        return success(declaration=d)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("수정", e)


@router.delete("/{decl_id}")
async def delete_decl(decl_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        await ImportDeclService.delete(decl_id, auth)
        logger.info(f"수입신고 기록 삭제: id={decl_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e)
