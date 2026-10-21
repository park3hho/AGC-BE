from tortoise import fields

from core.detail_page_config import DetailStatus, ExportPlatform, ReviewAction
from models.base import BaseModel


class DetailPage(BaseModel):
    """상세페이지 — 제품 1개 : 1개. S1~S5 문구·사진은 content(JSON), S6 공통 안내·등록번호는 DetailPageCommon.
    승인 = 지금 content + 공통 안내를 사람이 휴먼 체크로 확인함. 승인 뒤 내용이 바뀌면 검수 대기로 돌아간다."""

    product = fields.OneToOneField("models.Product", related_name="detail_page", on_delete=fields.CASCADE)
    content = fields.JSONField()                                       # 템플릿 칸 값 (schemas/detail_page.DetailContent)
    status = fields.CharEnumField(DetailStatus, max_length=20, default=DetailStatus.DRAFT)
    updated_by = fields.ForeignKeyField(
        "models.User", related_name="edited_detail_pages", null=True, on_delete=fields.SET_NULL
    )
    # 마지막 검수 (승인 또는 수정 요청) — 누가 · 언제 · 메모 · 체크한 항목
    reviewed_by = fields.ForeignKeyField(
        "models.User", related_name="reviewed_detail_pages", null=True, on_delete=fields.SET_NULL
    )
    reviewed_at = fields.DatetimeField(null=True)
    review_note = fields.TextField(null=True)
    review_checks = fields.JSONField(null=True)                        # 예전 기록용 (5개 체크리스트 폐지 후 항상 null)

    class Meta:
        table = "detail_page"


class DetailPageReview(BaseModel):
    """검수 기록 — 검수 요청 · 승인 · 수정 요청 · 자동 되돌림. 지우지 않는다."""

    page = fields.ForeignKeyField("models.DetailPage", related_name="reviews", on_delete=fields.CASCADE)
    action = fields.CharEnumField(ReviewAction, max_length=20)
    user = fields.ForeignKeyField(
        "models.User", related_name="detail_page_reviews", null=True, on_delete=fields.SET_NULL
    )
    note = fields.TextField(null=True)
    checks = fields.JSONField(null=True)

    class Meta:
        table = "detail_page_review"


class DetailPageExport(BaseModel):
    """상세 이미지 내보내기 — 승인된 상세페이지를 판매처 폭의 JPG 조각으로 저장한 기록. 판매처마다 버전이 1씩 오른다.
    content_hash = 그린 시점의 content + 공통 안내 해시 (지금 해시와 다르면 옛 이미지). 지우지 않는다."""

    page = fields.ForeignKeyField("models.DetailPage", related_name="exports", on_delete=fields.CASCADE)
    platform = fields.CharEnumField(ExportPlatform, max_length=20)
    version = fields.IntField()                                        # 판매처별 1, 2, 3 …
    content_hash = fields.CharField(max_length=64)                     # sha256 hex
    template = fields.CharField(max_length=50, default="")             # FE 템플릿 버전 (DETAIL_TEMPLATE_VERSION)
    files = fields.JSONField()                                         # [{url, width, height, size, sha256}] 순서대로
    created_by = fields.ForeignKeyField(
        "models.User", related_name="detail_page_exports", null=True, on_delete=fields.SET_NULL
    )

    class Meta:
        table = "detail_page_export"
        unique_together = (("page", "platform", "version"),)


class DetailPageCommon(BaseModel):
    """모든 상세페이지가 같이 쓰는 S6 해외구매대행 안내 + 등록번호. 행 1개 (id=1)."""

    reg_no = fields.CharField(max_length=50, default="")               # 수입식품등 인터넷 구매대행업 등록번호
    seller = fields.CharField(max_length=100, default="")              # 맨 아래 판매자 이름
    notice_title = fields.CharField(max_length=100, default="")
    notice = fields.JSONField()                                        # [{title, body}]
    updated_by = fields.ForeignKeyField(
        "models.User", related_name="edited_detail_commons", null=True, on_delete=fields.SET_NULL
    )

    class Meta:
        table = "detail_page_common"
