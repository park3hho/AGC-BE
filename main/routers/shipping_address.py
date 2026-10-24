import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.shipping_address import ShippingAddressCreate, ShippingAddressUpdate
from services.shipping.address_service import ShippingAddressService, courier_list

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shipping-addresses", tags=["ShippingAddress"])

# 보기 = research (배송비 화면과 같음) · 추가·수정·삭제 = account_edit (마켓에 걸린 회사 설정이라 관리자만)


def _fail(what: str, e: Exception):
    logger.error(f"출고지·반품지 {what} 실패: {e}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_addresses(auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(items=await ShippingAddressService.list(), couriers=courier_list())
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록 조회", e)


@router.post("")
async def create_address(body: ShippingAddressCreate, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))):
    try:
        item = await ShippingAddressService.create(body, actor_id=auth["user_id"])
        logger.info(f"출고지·반품지 추가: id={item['id']} by={auth['user_id']}")
        return success(address=item)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("추가", e)


@router.get("/{address_id}")
async def get_address(address_id: int, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(address=await ShippingAddressService.get(address_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("조회", e)


@router.patch("/{address_id}")
async def update_address(
    address_id: int, body: ShippingAddressUpdate, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))
):
    try:
        item = await ShippingAddressService.update(address_id, body)
        logger.info(f"출고지·반품지 수정: id={address_id} fields={sorted(body.model_fields_set)} by={auth['user_id']}")
        return success(address=item)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("수정", e)


@router.delete("/{address_id}")
async def delete_address(address_id: int, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))):
    try:
        await ShippingAddressService.delete(address_id)
        logger.info(f"출고지·반품지 삭제: id={address_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e)
