# core/auth_deps.py
# 인증·권한 의존성 (DESIGN.md §5)
#
#   auth=Depends(require_auth)                        로그인만
#   auth=Depends(require_feature(Feature.RESEARCH))   Feature 보유
#   auth=Depends(require_role(Role.ADMIN))            역할
#
# 세션에는 user_id · session_version · remember 만 둔다. 역할·활성 여부는 요청마다 DB 에서 다시 읽는다
#   → 관리자가 비활성화·역할 변경·비밀번호 변경을 하면 다음 요청부터 바로 반영.

import time

from fastapi import Depends, HTTPException, Request

from core.permissions import Feature, Role, has_feature
from core.session import REMEMBER_KEY
from models.user.user import User

SESSION_USER_KEY = "user_id"
SESSION_VERSION_KEY = "ver"
SESSION_TOUCH_KEY = "t"


def start_session(request: Request, user: User, remember: bool) -> None:
    request.session.clear()
    request.session.update({
        SESSION_USER_KEY: user.id,
        SESSION_VERSION_KEY: user.session_version,
        REMEMBER_KEY: bool(remember),
        SESSION_TOUCH_KEY: int(time.time()),
    })


def end_session(request: Request) -> None:
    request.session.clear()


async def current_user(request: Request) -> User | None:
    """세션의 사용자. 없거나 비활성·비밀번호 변경으로 무효면 세션을 비우고 None."""
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    user = await User.get_or_none(id=user_id)
    if not user or not user.active or user.session_version != request.session.get(SESSION_VERSION_KEY):
        request.session.clear()
        return None
    # 슬라이딩 — 세션을 다시 써야 Set-Cookie 가 나가고 서명 시각·Max-Age 가 갱신된다
    request.session[SESSION_TOUCH_KEY] = int(time.time())
    return user


async def require_auth(request: Request) -> dict:
    user = await current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return {"user_id": user.id, "role": user.role, "user": user}


def require_feature(feature: Feature):
    async def checker(auth: dict = Depends(require_auth)) -> dict:
        if not has_feature(auth["role"], feature):
            raise HTTPException(status_code=403, detail="권한이 없습니다.")
        return auth

    return checker


def require_role(role: Role):
    async def checker(auth: dict = Depends(require_auth)) -> dict:
        if auth["role"] != role:
            raise HTTPException(status_code=403, detail="권한이 없습니다.")
        return auth

    return checker
