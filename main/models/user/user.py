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


class ApiKey(BaseModel):
    """자동화용 API 키 (리서처 skill 등). 헤더 X-API-Key 로 받는다.
    원문은 발급할 때 한 번만 보여주고 DB 에는 sha256 해시만 둔다. 키로는 로그인·research 권한만 쓸 수 있다 (core/auth_deps.py)."""

    user = fields.ForeignKeyField("models.User", related_name="api_keys", on_delete=fields.CASCADE)  # 이 사용자로 동작
    name = fields.CharField(max_length=100)                       # 용도 메모 (예: 리서처 skill)
    key_prefix = fields.CharField(max_length=16)                  # 원문 앞부분 — 목록에서 어느 키인지 구분용
    key_hash = fields.CharField(max_length=64, unique=True)       # sha256(원문) hex
    active = fields.BooleanField(default=True)                    # False = 폐기
    last_used_at = fields.DatetimeField(null=True)                # 마지막 사용 시각
    # 서비스 키 (fin · mkt · shop) — 채워져 있으면 /internal/company 전용, 일반 API 는 403 (core/internal_services.py)
    service = fields.CharField(max_length=20, null=True)

    class Meta:
        table = "api_key"
