import logging

from fastapi import APIRouter, HTTPException, Request

from core.auth_deps import current_user, end_session, start_session
from core.response_utils import success, success_only
from schemas.auth import LoginRequest
from services.user.serializers import auth_user_dict
from services.user.user_service import UserService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    try:
        user = await UserService.authenticate(body)
        start_session(request, user, body.remember)
        logger.info(f"로그인: user_id={user.id} remember={body.remember}")
        return success(user=auth_user_dict(user))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"로그인 실패: {type(e).__name__}")     # 요청 본문(비밀번호)이 섞이지 않게 예외 종류만
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.post("/logout")
async def logout(request: Request):
    end_session(request)
    return success_only()


@router.get("/check")
async def check(request: Request):
    try:
        user = await current_user(request)
    except Exception as e:
        logger.error(f"로그인 확인 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return success(user=auth_user_dict(user))
