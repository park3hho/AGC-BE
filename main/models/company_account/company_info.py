from tortoise import fields

from models.base import BaseModel


class CompanyInfo(BaseModel):
    """회사 정보 › 기본 정보 — 로그인도 비밀값도 아닌 회사 정보 1건 (사업자등록번호, 인허가 번호, 계좌, 연락처, 서류).
    값은 숨기지 않는다. 만료일이 있어도 API 키(ApiCredential)와는 다른 개념이다 — 비밀값·재인증·허용 IP 가 없다."""

    category = fields.CharField(max_length=30)                    # 분류 — 자유 입력 (사업자 · 인허가·신고 · 계좌 · 연락처 · 서류 …)
    name = fields.CharField(max_length=100)                       # 이름 (예: 전자상거래업자부호)
    value = fields.CharField(max_length=500, null=True)           # 대표 값 — 서류처럼 파일만 있으면 비움
    details = fields.JSONField(default=list)                      # 세부 값 [{label, value}] — 은행·예금주·상호 등
    issuer = fields.CharField(max_length=100, null=True)          # 발급기관
    issued_on = fields.DateField(null=True)
    expires_on = fields.DateField(null=True)
    remind = fields.BooleanField(default=True)                    # 만료가 가까우면 홈 할 일에 띄울지
    url = fields.CharField(max_length=500, null=True)             # 관련 사이트 (발급·조회 페이지)
    link = fields.CharField(max_length=50, null=True)             # 앱에서 이 값을 쓰는 곳 (core/company_info_config.INFO_LINKS)
    sort = fields.SmallIntField(default=0)                        # 분류 안 순서
    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField(
        "models.User", related_name="created_company_infos", null=True, on_delete=fields.SET_NULL
    )
    deleted_at = fields.DatetimeField(null=True)                  # 소프트 삭제

    class Meta:
        table = "company_info"


class CompanyInfoFile(BaseModel):
    """기본 정보에 붙인 서류 파일 — PRIVATE_DIR 에 저장 (공개 /files 아님). 받기는 로그인한 account_view 만."""

    info = fields.ForeignKeyField("models.CompanyInfo", related_name="files", on_delete=fields.CASCADE)
    name = fields.CharField(max_length=200)                       # 올린 파일 이름 (보여주기용 — 저장 경로에는 쓰지 않는다)
    path = fields.CharField(max_length=300)                       # PRIVATE_DIR 기준 상대 경로
    size = fields.IntField()
    content_type = fields.CharField(max_length=50)

    class Meta:
        table = "company_info_file"
