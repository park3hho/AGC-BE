from tortoise import fields

from models.base import BaseModel


class CompanyAccount(BaseModel):
    """회사가 쓰는 외부 서비스 계정 (타오바오·쿠팡·네이버 등)."""

    platform = fields.CharField(max_length=100)                   # 플랫폼 이름 — 자유 입력 (예: 식품안전나라)
    url = fields.CharField(max_length=500, null=True)             # 홈페이지·로그인 주소 (http/https)
    login_id = fields.CharField(max_length=200)                   # 그 플랫폼의 로그인 아이디
    password_enc = fields.TextField()                             # Fernet 암호문 (core/account_crypto.py) — 목록·로그 노출 금지
    usages = fields.JSONField(default=list)                       # 용도 문자열 배열 (예: ["판매", "정산"])
    memo = fields.TextField(null=True)                            # 비고 (예: 연동된 휴대폰 번호) — 비밀값은 넣지 않는다
    created_by = fields.ForeignKeyField(
        "models.User", related_name="created_company_accounts", null=True, on_delete=fields.SET_NULL
    )
    # 소프트 삭제 — 비밀번호 열람 기록(CompanyAccountPasswordView)을 남기려고 행은 지우지 않는다
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "company_account"


class CompanyAccountPasswordView(BaseModel):
    """비밀번호 열람 기록 — 누가, 언제(created_at), 어느 계정을 봤는지. 지우지 않는다."""

    account = fields.ForeignKeyField(
        "models.CompanyAccount", related_name="password_views", on_delete=fields.CASCADE
    )
    user = fields.ForeignKeyField("models.User", related_name="password_views", on_delete=fields.RESTRICT)
    ip = fields.CharField(max_length=64, null=True)               # 요청 IP (프록시 뒤면 프록시 IP)

    class Meta:
        table = "company_account_password_view"
