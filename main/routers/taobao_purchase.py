import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_feature
from core.permissions import Feature
from core.purchase_config import CN_STATUS
from core.response_utils import success, success_only
from schemas.taobao_purchase import TaobaoPurchaseCreate, TaobaoPurchaseUpdate
from services.order.purchase_service import TaobaoPurchaseService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/taobao-purchases", tags=["TaobaoPurchase"])

# 타오바오 구매 · 중국 내 배송 — 주문과 같은 order 권한. 바꿀 때마다 연결된 마켓 주문의 추적 기록(OrderEvent)에 남는다.


def _fail(what: str, e: Exception, purchase_id=None):
    where = f" purchase_id={purchase_id}" if purchase_id is not None else ""
    logger.error(f"타오바오 구매 {what} 실패:{where} {type(e).__name__}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_purchases(
    order_id: Optional[int] = Query(default=None, ge=1),
    cn_status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=40),
    limit: int = Query(default=100, ge=1, le=500),
    include_test: bool = Query(default=False),
    auth=Depends(require_feature(Feature.ORDER)),
):
    if cn_status and cn_status not in CN_STATUS:
        raise HTTPException(status_code=400, detail="중국 배송 상태가 올바르지 않습니다.")
    try:
        items = await TaobaoPurchaseService.list(order_id, cn_status, q, limit, include_test)
        return success(items=items, cn_status=CN_STATUS)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록 조회", e)


@router.post("")
async def create_purchase(body: TaobaoPurchaseCreate, auth=Depends(require_feature(Feature.ORDER))):
    try:
        p = await TaobaoPurchaseService.create(body, auth)
        logger.info(f"타오바오 구매 추가: purchase_id={p['id']} order_id={p['order']['id']} by={auth['user_id']}")
        return success(purchase=p)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("추가", e)


@router.get("/{purchase_id}")
async def get_purchase(purchase_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(purchase=await TaobaoPurchaseService.get(purchase_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("조회", e, purchase_id)


@router.patch("/{purchase_id}")
async def update_purchase(
    purchase_id: int, body: TaobaoPurchaseUpdate, auth=Depends(require_feature(Feature.ORDER))
):
    try:
        p = await TaobaoPurchaseService.update(purchase_id, body, auth)
        logger.info(f"타오바오 구매 수정: purchase_id={purchase_id} fields={sorted(body.model_fields_set)} by={auth['user_id']}")
        return success(purchase=p)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("수정", e, purchase_id)


@router.delete("/{purchase_id}")
async def delete_purchase(purchase_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        await TaobaoPurchaseService.delete(purchase_id, auth)
        logger.info(f"타오바오 구매 삭제: purchase_id={purchase_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e, purchase_id)


# ---------------------------------------------------------------- 소포 (2026-11-19)
# 판매처가 한 구매를 여러 소포로 나눠 보낸 경우. 소포가 기록돼 있으면 전부 입고돼야 구매가 '창고 입고'가 된다.
from schemas.ops import PackageIn, PackagePatch   # noqa: E402
from services.order import package_service   # noqa: E402


@router.get("/{purchase_id}/packages")
async def list_packages(purchase_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(**await package_service.list_packages(purchase_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("소포 목록", e, purchase_id)


@router.post("/{purchase_id}/packages")
async def add_package(purchase_id: int, body: PackageIn, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(**await package_service.add(purchase_id, body.model_dump(), auth))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("소포 추가", e, purchase_id)


@router.patch("/packages/{package_id}")
async def patch_package(package_id: int, body: PackagePatch, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(**await package_service.patch(package_id, body.model_dump(exclude_unset=True), auth))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("소포 수정", e)


@router.delete("/packages/{package_id}")
async def delete_package(package_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(**await package_service.delete(package_id, auth))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("소포 삭제", e)
