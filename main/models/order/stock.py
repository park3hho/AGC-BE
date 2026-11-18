from tortoise import fields

from models.base import BaseModel


class JiyunStock(BaseModel):
    """집운 가용재고 1건 = 고객이 취소했지만 환불받지 못한 타오바오 소포 1개 (2026-11-18).

    판매처가 이미 보낸 뒤 고객이 취소하면 타오바오 구매(¥)는 바로 환불되지 않는다. 그 소포를 반품하는 대신
    집운 창고에 두었다가, 같은 상품(같은 SKU)의 다음 주문이 오면 새로 사지 않고 이 소포를 그 주문에 붙여 보낸다.

    흐름: available(보관 — 판매처→창고 이동 중이거나 창고에 있음) → used(다른 주문에 씀) / returned(판매처 반품·환불) / written_off(버림·손실)
    쓸 때: 타오바오 구매(TaobaoPurchase.order)를 새 주문으로 옮긴다 → 원가가 새 주문에 붙고, 취소 주문은 손실 0.
    보관 중(available)인 구매는 매출 현황에서 취소 주문 손실로 세지 않는다 (재고 = 자산). written_off 면 다시 손실로 센다."""

    purchase = fields.ForeignKeyField("models.TaobaoPurchase", related_name="stock_entries", on_delete=fields.RESTRICT)
    source_order = fields.ForeignKeyField("models.MarketOrder", related_name="stock_sources", null=True, on_delete=fields.SET_NULL)  # 취소된 원래 주문
    used_order = fields.ForeignKeyField("models.MarketOrder", related_name="stock_uses", null=True, on_delete=fields.SET_NULL)      # 이 소포를 쓴 주문

    # 무엇인지 — 원래 주문의 판매자 상품코드(SKU) 그대로: PR-yymmdd-xxxx-{옵션id}x{묶음수}
    sku = fields.CharField(max_length=60, null=True, index=True)
    product_code = fields.CharField(max_length=20, null=True, index=True)   # PR-yymmdd-xxxx
    option_id = fields.IntField(null=True)                                  # 조사 옵션 id
    bundle_qty = fields.IntField(default=1)                                 # 묶음 수 (2박스 = 2)
    label = fields.CharField(max_length=200)                                # 사람이 읽는 이름 (상품 · 옵션)

    status = fields.CharField(max_length=12, default="available")   # available · used · returned · written_off
    cost_cny = fields.DecimalField(max_digits=12, decimal_places=2, null=True)   # 타오바오 결제 위안 (구매 기록에서)
    cost_krw = fields.IntField(null=True)                                         # 실제 청구 원화 (구매 기록에서)
    expires_on = fields.DateField(null=True)                        # 유통기한 (알면)
    used_at = fields.DatetimeField(null=True)
    closed_at = fields.DatetimeField(null=True)                     # used · returned · written_off 로 바뀐 때
    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField("models.User", related_name="created_stocks", null=True, on_delete=fields.SET_NULL)
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "jiyun_stock"
        table_description = "집운 가용재고 — 고객 취소 뒤 환불 못 받은 타오바오 소포를 창고에 두고 같은 SKU 다음 주문에 씀 (2026-11-18)"
