import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_auth, require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.product import ProductCreate, ProductUpdate
from services.product.product_service import ProductService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/products", tags=["Product"])


@router.post("")
async def create_product(body: ProductCreate, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(product=await ProductService.create(body))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"제품 등록 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_products(
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    auth=Depends(require_auth),
):
    try:
        return success(**await ProductService.list(q.strip() if q else None, page, size))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"제품 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/next-code")    # ★ /{product_id} 보다 먼저 선언해야 한다
async def get_next_product_code(auth=Depends(require_auth)):
    try:
        return success(code=await ProductService.next_code())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"다음 제품 코드 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/{product_id}")
async def get_product(product_id: int, auth=Depends(require_auth)):
    try:
        return success(**await ProductService.get(product_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"제품 상세 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.patch("/{product_id}")
async def update_product(product_id: int, body: ProductUpdate, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(product=await ProductService.update(product_id, body))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"제품 수정 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.delete("/{product_id}")
async def delete_product(product_id: int, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        await ProductService.delete(product_id)
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"제품 삭제 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
