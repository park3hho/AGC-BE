from tortoise import fields

from models.base import BaseModel


class TaobaoPurchase(BaseModel):
    """타오바오 구매 1건 = 타오바오 주문번호 1개 (판매처 1곳) + 그 물건이 집운 창고까지 오는 중국 내 배송.
    마켓 주문과는 다대다 (TaobaoPurchaseLink): 한 마켓 주문을 여러 타오바오 주문으로 사거나(품절·나눠 구매),
    타오바오 주문 하나로 여러 마켓 주문을 같이 살 수 있다. 바꿀 때마다 연결된 마켓 주문마다 OrderEvent 를 남긴다."""

    # 구매
    taobao_order_no = fields.CharField(max_length=40, null=True)    # 타오바오 주문번호 (订单号) — 살아 있는 구매끼리 겹치지 않게 (서비스에서 409)
    shop_name = fields.CharField(max_length=200, null=True)         # 판매처(가게) 이름
    item_url = fields.CharField(max_length=500, null=True)          # 산 상품 페이지
    items = fields.JSONField(default=list)                          # [{name, qty, price_cny}] — 옵션(맛·용량)·수량·단가
    paid_cny = fields.DecimalField(max_digits=12, decimal_places=2, null=True)   # 실제 결제 위안 (할인·배송비 반영 합계)
    purchased_at = fields.DatetimeField(null=True)
    purchased_by = fields.ForeignKeyField(
        "models.User", related_name="taobao_purchases", null=True, on_delete=fields.SET_NULL
    )

    # 중국 내 배송 (판매처 → 집운 창고)
    cn_status = fields.CharField(max_length=20, default="ordered")  # core/purchase_config.CN_STATUS
    shipped_at = fields.DatetimeField(null=True)                    # 판매처 발송
    cn_courier = fields.CharField(max_length=50, null=True)         # 중국 택배사 (中通·圆通·顺丰 …)
    cn_tracking_no = fields.CharField(max_length=60, null=True)     # 중국 운송장 번호
    arrived_at = fields.DatetimeField(null=True)                    # 집운 창고 입고
    warehouse_ref = fields.CharField(max_length=60, null=True)      # 집운 입고 번호 (있으면)
    status_source = fields.CharField(max_length=10, default="manual")   # manual(사람·에이전트 입력) · poll(나중에 폴링이 채움)
    status_checked_at = fields.DatetimeField(null=True)             # 폴링이 마지막으로 확인한 때

    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField(
        "models.User", related_name="created_taobao_purchases", null=True, on_delete=fields.SET_NULL
    )
    deleted_at = fields.DatetimeField(null=True)                    # 소프트 삭제 — 추적 기록은 남는다

    class Meta:
        table = "taobao_purchase"


class TaobaoPurchaseLink(BaseModel):
    """타오바오 구매 ↔ 마켓 주문 연결 (다대다)."""

    purchase = fields.ForeignKeyField("models.TaobaoPurchase", related_name="links", on_delete=fields.CASCADE)
    order = fields.ForeignKeyField("models.MarketOrder", related_name="purchase_links", on_delete=fields.RESTRICT)
    quantity = fields.IntField(null=True)                           # 이 마켓 주문 몫으로 산 수량 (모르면 비움)

    class Meta:
        table = "taobao_purchase_link"
        unique_together = (("purchase", "order"),)
