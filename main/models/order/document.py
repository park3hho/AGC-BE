from tortoise import fields

from models.base import BaseModel


class OrderDocument(BaseModel):
    """주문 증빙 파일 — 고객 결제 금액에서 빠져나간 돈의 근거 (2026-10-29).
    타오바오 구매 영수증(주문상세 PDF) · 집운 배송비 결제 내역 · 마켓 정산 내역 · 카드 승인 내역 등.
    고객 주문(MarketOrder) 1건에 붙고, 어느 비용 줄의 근거인지는 kind 와 purchase/jiyun 으로 나눈다.
    파일은 PRIVATE_DIR 에 둔다 (공개 /files 아님) — 받기는 로그인한 order 권한만."""

    order = fields.ForeignKeyField("models.MarketOrder", related_name="documents", on_delete=fields.RESTRICT)
    kind = fields.CharField(max_length=20)                           # core/order_document_config.DOC_KINDS — purchase · jiyun · market · card · other
    purchase = fields.ForeignKeyField(
        "models.TaobaoPurchase", related_name="documents", null=True, on_delete=fields.SET_NULL
    )
    jiyun = fields.ForeignKeyField(
        "models.JiyunShipment", related_name="documents", null=True, on_delete=fields.SET_NULL
    )
    name = fields.CharField(max_length=200)                          # 올린 파일 이름 (보여주기용)
    path = fields.CharField(max_length=300)                          # PRIVATE_DIR 기준 상대 경로
    size = fields.IntField()
    content_type = fields.CharField(max_length=50)
    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField(
        "models.User", related_name="created_order_documents", null=True, on_delete=fields.SET_NULL
    )
    deleted_at = fields.DatetimeField(null=True)                     # 소프트 삭제 (파일은 남긴다)

    class Meta:
        table = "order_document"
