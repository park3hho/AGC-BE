from tortoise import fields

from models.base import BaseModel


class ShippingAddress(BaseModel):
    """출고지·반품지 주소록 — 실제 장소 1곳 = 1행. 마켓(네이버·쿠팡)마다 따로 받은 주소 코드를 market_codes 에 묶어 둔다.
    상품 등록 때 기본 출고지·반품지(defaults)의 마켓 코드를 쓴다. 구매대행은 출고지가 해외(배대지)여야 한다."""

    name = fields.CharField(max_length=100)                       # 이름 (예: 집운 웨이하이 배대지)
    country = fields.CharField(max_length=2, default="KR")        # ISO 국가 코드 — KR 이 아니면 해외 주소
    zip_code = fields.CharField(max_length=20, null=True)
    address = fields.CharField(max_length=300)                    # 기본 주소 (해외는 현지어·영문 그대로)
    address_detail = fields.CharField(max_length=300, null=True)  # 상세 주소 · 사서함 번호
    phone = fields.CharField(max_length=40, null=True)
    uses = fields.JSONField(default=list)                         # 용도 ["outbound", "return"] — 출고지 · 반품(교환)지
    defaults = fields.JSONField(default=list)                     # 기본으로 쓰는 용도 (uses 의 부분집합, 용도마다 1곳만)
    market_codes = fields.JSONField(default=list)                 # [{market, use, code, name}] — 마켓 주소록 번호
    route = fields.JSONField(null=True)                           # 배송 경로 (해외 출고지) — 물류사·항구·국내 택배사·송장 시점. schemas.RouteIn
    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField(
        "models.User", related_name="created_shipping_addresses", null=True, on_delete=fields.SET_NULL
    )
    deleted_at = fields.DatetimeField(null=True)                  # 소프트 삭제 — 등록 기록이 코드를 참조할 수 있어 행은 남긴다

    class Meta:
        table = "shipping_address"
