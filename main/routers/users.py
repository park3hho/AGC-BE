import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from schemas.user import UserCreate, UserUpdate
from services.user.user_service import UserService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["User"])


@router.get("")
async def list_users(auth=Depends(require_feature(Feature.USER_MANAGE))):
    try:
        return success(items=await UserService.list())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"사용자 목록 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.post("")
async def create_user(body: UserCreate, auth=Depends(require_feature(Feature.USER_MANAGE))):
    try:
        user = await UserService.create(body)
        logger.info(f"사용자 추가: user_id={user['id']} role={user['role']} by={auth['user_id']}")
        return success(user=user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"사용자 추가 실패: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.patch("/{user_id}")
async def update_user(user_id: int, body: UserUpdate, auth=Depends(require_feature(Feature.USER_MANAGE))):
    try:
        user = await UserService.update(user_id, body, actor_id=auth["user_id"])
        changed = [k for k in ("active", "role", "password") if getattr(body, k) is not None]
        logger.info(f"사용자 수정: user_id={user_id} fields={changed} by={auth['user_id']}")
        return success(user=user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"사용자 수정 실패: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
