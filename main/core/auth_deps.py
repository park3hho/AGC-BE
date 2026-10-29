# core/auth_deps.py
# 인증·권한 의존성 (DESIGN.md §5)
#
#   auth=Depends(require_auth)                        로그인만
#   auth=Depends(require_feature(Feature.RESEARCH))   Feature 보유
#   auth=Depends(require_role(Role.ADMIN))            역할
#
# API 키 (헤더 X-API-Key) — 리서처 skill 같은 자동화용. 세션을 만들지 않는다.
#   키로는 로그인 · research 권한만 쓸 수 있다 (API_KEY_FEATURES). 역할이 admin 이어도 그 밖은 403.
#   발급·폐기는 scripts/api_key.py (BE PC 에서만).
#
# 세션에는 user_id · session_version · remember 만 둔다. 역할·활성 여부는 요청마다 DB 에서 다시 읽는다
#   → 관리자가 비활성화·역할 변경·비밀번호 변경을 하면 다음 요청부터 바로 반영.

import hashlib
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request

from core.permissions import Feature, Role, has_feature
from core.session import REMEMBER_KEY
from models.user.user import ApiKey, User

SESSION_USER_KEY = "user_id"
SESSION_VERSION_KEY = "ver"
SESSION_TOUCH_KEY = "t"

API_KEY_HEADER = "X-API-Key"
API_KEY_FEATURES = frozenset({Feature.RESEARCH})
_API_KEY_TOUCH_EVERY = timedelta(minutes=5)     # last_used_at 은 5분에 한 번만 쓴다 (요청마다 쓰지 않게)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _active_key(raw: str) -> ApiKey | None:
    key = await ApiKey.get_or_none(key_hash=hash_api_key(raw.strip()), active=True).select_related("user")
    if not key or not key.user.active:
        return None
    now = datetime.now(timezone.utc)
    if key.last_used_at is None or now - key.last_used_at > _API_KEY_TOUCH_EVERY:
        key.last_used_at = now
        await key.save(update_fields=["last_used_at"])
    return key


async def _user_from_api_key(raw: str) -> User | None:
    key = await _active_key(raw)
    if key and key.service:
        # 서비스 키(fin·mkt·shop)는 /internal/company 전용 — 일반 API 에서는 쓸 수 없다
        raise HTTPException(status_code=403, detail="서비스 키로는 쓸 수 없는 API 입니다.")
    return key.user if key else None


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
    raw_key = request.headers.get(API_KEY_HEADER)
    if raw_key is not None:
        # 키를 보냈으면 키로만 판단한다 (틀린 키로 세션에 기대지 않는다)
        user = await _user_from_api_key(raw_key)
        if not user:
            raise HTTPException(status_code=401, detail="API 키가 올바르지 않거나 폐기되었습니다.")
        return {"user_id": user.id, "role": user.role, "user": user, "via_api_key": True}
    user = await current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return {"user_id": user.id, "role": user.role, "user": user, "via_api_key": False}


async def require_service(request: Request) -> dict:
    """/internal/company 전용 — 서비스 키(api_key.service)만 통과. 사람 세션·일반 API 키는 401/403.
    nginx 를 거친 요청(X-Real-IP · X-Forwarded-For)은 밖에서 온 것이라 404 — nginx 차단과 같이 이중으로 막는다."""
    if request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for"):
        raise HTTPException(status_code=404, detail="Not Found")
    raw = request.headers.get(API_KEY_HEADER)
    if not raw:
        raise HTTPException(status_code=401, detail="서비스 키가 필요합니다.")
    key = await _active_key(raw)
    if not key:
        raise HTTPException(status_code=401, detail="API 키가 올바르지 않거나 폐기되었습니다.")
    if not key.service:
        raise HTTPException(status_code=403, detail="서비스 키가 아닙니다.")
    return {"service": key.service, "user_id": key.user_id, "key_id": key.id}


def require_feature(feature: Feature):
    async def checker(auth: dict = Depends(require_auth)) -> dict:
        if auth["via_api_key"] and feature not in API_KEY_FEATURES:
            raise HTTPException(status_code=403, detail="API 키로는 쓸 수 없는 기능입니다.")
        if not has_feature(auth["role"], feature):
            raise HTTPException(status_code=403, detail="권한이 없습니다.")
        return auth

    return checker


def require_role(role: Role):
    async def checker(auth: dict = Depends(require_auth)) -> dict:
        if auth["via_api_key"] or auth["role"] != role:
            raise HTTPException(status_code=403, detail="권한이 없습니다.")
        return auth

    return checker
