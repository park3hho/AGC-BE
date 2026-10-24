from tortoise import fields

from core.pricing_config import Platform
from models.base import BaseModel


class MarketListing(BaseModel):
    """마켓 등록 — 제품 1개를 판매처(쿠팡·네이버)에 올린 상품 1건. 제품 1 : N
    (예: 쿠팡에 맛별로 나눠 올리면 여러 건). 업로드 일시 = listed_at (마켓이 알려준 등록 시각, 직접 입력 가능).
    쿠팡은 '쿠팡에서 불러오기'가 externalVendorSku(`{제품 코드}-{옵션 id}`)로 제품을 찾아 채운다."""

    product = fields.ForeignKeyField("models.Product", related_name="listings", on_delete=fields.CASCADE)
    platform = fields.CharEnumField(Platform, max_length=20)
    market_product_id = fields.CharField(max_length=50)           # 쿠팡 sellerProductId · 네이버 원상품번호
    title = fields.CharField(max_length=300, null=True)           # 마켓에 올린 상품명
    url = fields.CharField(max_length=1000, null=True)            # 구매자가 보는 상품 페이지
    status = fields.CharField(max_length=30, null=True)           # 마켓이 준 상태 (승인완료 등) · 직접 입력이면 비움
    listed_at = fields.DatetimeField(null=True)                   # 업로드 일시
    items = fields.JSONField(null=True)                           # [{option_id, name, sale_price, market_item_id, sku}]
    source = fields.CharField(max_length=10, default="manual")    # api(마켓에서 불러옴) · manual(직접 입력)
    synced_at = fields.DatetimeField(null=True)                   # 마지막으로 마켓에서 불러온 시각
    memo = fields.CharField(max_length=500, null=True)
    created_by = fields.ForeignKeyField(
        "models.User", related_name="created_listings", null=True, on_delete=fields.SET_NULL
    )
    deleted_at = fields.DatetimeField(null=True)                  # 소프트 삭제 — 불러오기도 다시 살리지 않는다

    class Meta:
        table = "market_listing"
        unique_together = (("platform", "market_product_id"),)
