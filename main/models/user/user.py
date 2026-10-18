from tortoise import fields

from models.base import BaseModel


class User(BaseModel):
    """로그인 계정 (사람). 역할은 core.permissions.Role 값."""

    username = fields.CharField(max_length=50, unique=True)       # 로그인 아이디 (소문자로 저장)
    name = fields.CharField(max_length=50)                        # 표시 이름
    password_hash = fields.CharField(max_length=100)              # bcrypt 해시 — 응답에 절대 포함 금지
    role = fields.CharField(max_length=20)                        # admin / member
    active = fields.BooleanField(default=True)                    # False = 사용 중지 (세션 즉시 차단)
    session_version = fields.IntField(default=1)                  # 비밀번호 바꿀 때 +1 → 기존 세션 무효

    class Meta:
        table = "app_user"     # "user" 는 Postgres 예약어
