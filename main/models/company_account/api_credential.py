from tortoise import fields

from models.base import BaseModel


class ApiCredential(BaseModel):
    """회사가 쓰는 외부 API 키 묶음 (네이버 커머스API · 쿠팡 OpenAPI 등). 로그인 계정(CompanyAccount)과 따로 둔다.
    키에는 만료일·재인증 기간·허용 IP 가 있어서 관리 방식이 다르다."""

    service = fields.CharField(max_length=100)                    # 서비스 이름 — 자유 입력
    url = fields.CharField(max_length=500, null=True)             # 콘솔·발급 페이지
    public_values = fields.JSONField(default=list)                # 공개값 [{label, value}] — 앱 ID·업체코드 등 그냥 보여도 되는 것
    issued_on = fields.DateField(null=True)                       # 발급일 (모르면 비움)
    expires_on = fields.DateField(null=True)                      # 만료일 — 지나면 키를 다시 받아야 한다
    reauth_from = fields.DateField(null=True)                     # 재인증 기간 시작 (예: 네이버 커머스API 앱 인증)
    reauth_to = fields.DateField(null=True)                       # 재인증 기간 끝 — 놓치면 정지
    allowed_ips = fields.JSONField(default=list)                  # 호출 허용 IP 목록
    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField(
        "models.User", related_name="created_api_credentials", null=True, on_delete=fields.SET_NULL
    )
    deleted_at = fields.DatetimeField(null=True)                  # 소프트 삭제 — 열람 기록을 남기려고 행은 지우지 않는다

    class Meta:
        table = "api_credential"


class ApiCredentialSecret(BaseModel):
    """비밀값 1개 (시크릿·Access Key·Secret Key 등). 값은 Fernet 암호문 — 목록·로그 노출 금지."""

    credential = fields.ForeignKeyField("models.ApiCredential", related_name="secrets", on_delete=fields.CASCADE)
    label = fields.CharField(max_length=50)                       # 이름 (예: Secret Key)
    value_enc = fields.TextField()                                # core/account_crypto.py 로 암호화
    sort = fields.SmallIntField(default=0)                        # 화면 순서

    class Meta:
        table = "api_credential_secret"


class ApiCredentialSecretView(BaseModel):
    """비밀값 열람 기록 — 누가, 언제(created_at), 어느 비밀값을 봤는지. 지우지 않는다."""

    secret = fields.ForeignKeyField("models.ApiCredentialSecret", related_name="views", on_delete=fields.CASCADE)
    user = fields.ForeignKeyField("models.User", related_name="api_secret_views", on_delete=fields.RESTRICT)
    ip = fields.CharField(max_length=64, null=True)

    class Meta:
        table = "api_credential_secret_view"
