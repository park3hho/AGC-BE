from tortoise import fields

from models.base import BaseModel


class TaobaoPurchase(BaseModel):
    """타오바오 구매 1건 = 타오바오 주문번호 1개. 고객 주문(MarketOrder) 1건에 붙는 기록.
    기본은 고객 주문 1건 = 타오바오 주문 1건 (같은 고객 주문에 여러 개 붙는 것도 막지 않는다).
    중국 내 배송(판매처 → 집운 창고)까지 담는다. 집운 쪽 매칭(입고 번호 등)은 나중에 따로.
    바꿀 때마다 그 고객 주문의 OrderEvent 에 이전값 → 새값을 남긴다."""

    order = fields.ForeignKeyField("models.MarketOrder", related_name="taobao_purchases", on_delete=fields.RESTRICT)
    taobao_order_no = fields.CharField(max_length=40)               # 타오바오 주문번호 (订单号) — 살아 있는 구매끼리 겹치지 않게 (서비스에서 409)

    # 구매 (선택 입력)
    shop_name = fields.CharField(max_length=200, null=True)         # 판매처(가게) 이름
    item_url = fields.CharField(max_length=500, null=True)          # 산 상품 페이지
    items = fields.JSONField(default=list)                          # [{name, qty, price_cny}] — 옵션(맛·용량)·수량·단가
    paid_cny = fields.DecimalField(max_digits=12, decimal_places=2, null=True)   # 실제 결제 위안 (할인·배송비 반영 합계)
    purchased_at = fields.DatetimeField(null=True)

    # 실제 결제 — 결제창 금액(통화 그대로)과 카드사·카카오페이가 실제로 청구한 원화 (2026-10-25)
    pay_method = fields.CharField(max_length=20, null=True)         # core/purchase_config.PAY_METHOD — card · kakaopay · alipay · other
    pay_currency = fields.CharField(max_length=3, null=True)        # 결제창 통화 USD · KRW · CNY
    pay_amount = fields.DecimalField(max_digits=12, decimal_places=2, null=True)  # 결제창 금액 (타오바오 결제 수수료 포함)
    charged_krw = fields.IntField(null=True)                        # 실제 청구 원화 (카드 해외수수료 등 포함)
    charged_status = fields.CharField(max_length=10, default="none")  # none 모름 · approved 승인 금액 · settled 청구 확정
    charged_at = fields.DatetimeField(null=True)                    # 승인(결제) 일시
    charged_source = fields.CharField(max_length=100, null=True)    # 어디서 확인했는지 (카드사 승인내역 · 카카오페이 결제내역 등)
    purchased_by = fields.ForeignKeyField(
        "models.User", related_name="taobao_purchases", null=True, on_delete=fields.SET_NULL
    )

    # 중국 내 배송 (판매처 → 집운 창고, 선택 입력)
    cn_status = fields.CharField(max_length=20, default="ordered")  # core/purchase_config.CN_STATUS
    shipped_at = fields.DatetimeField(null=True)                    # 판매처 발송
    cn_courier = fields.CharField(max_length=50, null=True)         # 중국 택배사 (中通·圆通·顺丰 …)
    cn_tracking_no = fields.CharField(max_length=60, null=True)     # 중국 운송장 번호
    arrived_at = fields.DatetimeField(null=True)                    # 집운 창고 입고
    status_source = fields.CharField(max_length=10, default="manual")   # manual(사람·에이전트 입력) · poll(나중에 폴링이 채움)
    status_checked_at = fields.DatetimeField(null=True)             # 폴링이 마지막으로 확인한 때

    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField(
        "models.User", related_name="created_taobao_purchases", null=True, on_delete=fields.SET_NULL
    )
    deleted_at = fields.DatetimeField(null=True)                    # 소프트 삭제 — 추적 기록은 남는다

    class Meta:
        table = "taobao_purchase"
