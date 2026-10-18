from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from core.permissions import Role
from models.user.user import User
from schemas.auth import LoginRequest
from schemas.user import UserCreate, UserUpdate
from services.user.password import hash_password, verify_password
from services.user.serializers import user_dict


class UserService:
    @staticmethod
    async def authenticate(body: LoginRequest) -> User:
        user = await User.get_or_none(username=body.username)
        if not verify_password(body.password, user.password_hash if user else None):
            raise HTTPException(status_code=400, detail="아이디나 비밀번호가 맞지 않습니다.")
        if not user.active:     # 비밀번호가 맞을 때만 알려준다
            raise HTTPException(status_code=403, detail="사용이 멈춘 계정입니다. 관리자에게 문의해주세요.")
        return user

    @staticmethod
    async def list() -> list[dict]:
        return [user_dict(u) for u in await User.all().order_by("id")]

    @staticmethod
    async def create(body: UserCreate) -> dict:
        if await User.exists(username=body.username):
            raise HTTPException(status_code=409, detail="이미 있는 아이디입니다.")
        try:
            u = await User.create(
                username=body.username,
                name=body.name,
                password_hash=hash_password(body.password),
                role=body.role.value,
            )
        except IntegrityError:      # 동시에 같은 아이디로 만든 경우
            raise HTTPException(status_code=409, detail="이미 있는 아이디입니다.")
        return user_dict(u)

    @staticmethod
    async def update(user_id: int, body: UserUpdate, actor_id: int) -> dict:
        async with in_transaction():
            u = await User.get_or_none(id=user_id).select_for_update()
            if not u:
                raise HTTPException(status_code=404, detail="사용자를 찾지 못했습니다.")

            if user_id == actor_id:
                if body.active is False:
                    raise HTTPException(status_code=400, detail="자기 자신은 비활성화할 수 없습니다.")
                if body.role is not None and body.role.value != u.role:
                    raise HTTPException(status_code=400, detail="자기 역할은 바꿀 수 없습니다.")

            demoting = u.role == Role.ADMIN and u.active and (
                body.active is False or (body.role is not None and body.role != Role.ADMIN)
            )
            if demoting:
                # 관리자 행을 잠가서 두 관리자가 서로를 동시에 내리는 경우도 막는다
                admins = await User.filter(role=Role.ADMIN.value, active=True).select_for_update()
                if len(admins) <= 1:
                    raise HTTPException(status_code=400, detail="마지막 관리자는 비활성화하거나 직원으로 바꿀 수 없습니다.")

            if body.active is not None:
                u.active = body.active
            if body.role is not None:
                u.role = body.role.value
            if body.password is not None:
                u.password_hash = hash_password(body.password)
                u.session_version += 1      # 기존 세션 모두 무효
            await u.save()
        return user_dict(u)
