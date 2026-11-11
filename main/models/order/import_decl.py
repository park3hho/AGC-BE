from tortoise import fields

from models.base import BaseModel


class ImportDeclaration(BaseModel):
    """수입식품 구매대행 수입신고 1건 = 유니패스 '인터넷 구매대행 수입식품등의 수입신고서' 1장 (2026-11-11).

    받는 사람 1명 · B/L 1개마다 통관 전에 낸다 (시행규칙 제27조 제2항, playbook import-declaration.md).
    같은 고객 주문 여러 건이 한 상자(같은 B/L)로 오면 신고서 1장에 품목을 같이 적고, 그 주문들을 orders 로 묶는다.
    신고서 화면 캡처·PDF 는 주문 증빙(OrderDocument kind=import_decl)으로 올린다.
    바꿀 때마다 묶인 주문들의 추적 기록(OrderEvent import_decl_*)에 남는다."""

    orders = fields.ManyToManyField("models.MarketOrder", related_name="import_declarations",
                                    through="import_declaration_order")
    decl_no = fields.CharField(max_length=30, null=True)            # 유니패스 신청번호 WCANB-26-… (채번 뒤)
    receipt_no = fields.CharField(max_length=40, null=True)         # 식약처 접수번호 (접수 뒤)
    kind = fields.CharField(max_length=10, default="pre")           # pre 사전신고(입항 전) · main 본신고(입항 후)
    status = fields.CharField(max_length=12, default="sent")        # core/import_decl_config.DECL_STATUS
    agency_code = fields.CharField(max_length=10, null=True)        # 신고기관 — 인천항 해상 = 1471290 미추홀수입식품검사소
    bl_no = fields.CharField(max_length=60, null=True)              # H B/L (집운 국제 운송장)
    vessel = fields.CharField(max_length=60, null=True)             # 선(기)명
    arrival_date = fields.DateField(null=True)                      # 입항일자
    warehouse_code = fields.CharField(max_length=20, null=True)     # 보관창고 (02002004 인천세관 지정장치장)
    consignee = fields.CharField(max_length=40, null=True)          # 수하인 — 가린 이름만 (원본은 주문에)
    items = fields.JSONField(default=list)                          # [{name_en, maker_en, country, qty, unit}]
    seller_site = fields.CharField(max_length=300, null=True)       # 신고인 사이트 (판매한 마켓 상품 주소)
    shipper_site = fields.CharField(max_length=300, null=True)      # 송하인 사이트 (구매한 타오바오 상품 주소)
    sent_at = fields.DatetimeField(null=True)                       # 전송
    accepted_at = fields.DatetimeField(null=True)                   # 접수
    approved_at = fields.DatetimeField(null=True)                   # 수리
    result = fields.TextField(null=True)                            # 처리 결과 · 보완 요청 내용
    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField("models.User", related_name="created_import_declarations", null=True,
                                        on_delete=fields.SET_NULL)
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "import_declaration"
