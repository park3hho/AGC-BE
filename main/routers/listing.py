import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_auth, require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.listing import ListingCreate, ListingUpdate
from services.product.listing_service import ListingService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/listings", tags=["Listing"])

# 마켓 등록 기록 — 보기는 로그인만, 추가·수정·삭제·불러오기는 listing 권한 (API 키 불가)


def _fail(what: str, e: Exception, listing_id=None):
    where = f" listing_id={listing_id}" if listing_id is not None else ""
    logger.error(f"마켓 등록 {what} 실패:{where} {type(e).__name__}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_listings(product_id: Optional[int] = Query(default=None, ge=1), auth=Depends(require_auth)):
    try:
        return success(items=await ListingService.list(product_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록 조회", e)


@router.post("/sync/coupang")    # ★ /{listing_id} 보다 먼저
async def sync_coupang(dry_run: bool = Query(default=False), auth=Depends(require_feature(Feature.LISTING))):
    try:
        r = await ListingService.sync_coupang(dry_run)
        logger.info(
            f"쿠팡 상품 불러오기: total={r['total']} created={r['created']} updated={r['updated']} "
            f"unmatched={len(r['unmatched'])} dry_run={dry_run} by={auth['user_id']}"
        )
        return success(**r)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("쿠팡 불러오기", e)


@router.post("")
async def create_listing(body: ListingCreate, auth=Depends(require_feature(Feature.LISTING))):
    try:
        x = await ListingService.create(body, auth)
        logger.info(f"마켓 등록 추가: listing_id={x['id']} product_id={x['product_id']} by={auth['user_id']}")
        return success(listing=x)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("추가", e)


@router.patch("/{listing_id}")
async def update_listing(listing_id: int, body: ListingUpdate, auth=Depends(require_feature(Feature.LISTING))):
    try:
        return success(listing=await ListingService.update(listing_id, body))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("수정", e, listing_id)


@router.delete("/{listing_id}")
async def delete_listing(listing_id: int, auth=Depends(require_feature(Feature.LISTING))):
    try:
        await ListingService.delete(listing_id)
        logger.info(f"마켓 등록 삭제: listing_id={listing_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e, listing_id)
