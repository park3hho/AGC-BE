from tortoise import fields

from models.base import BaseModel


class JiyunShipment(BaseModel):
    """집운 기록 1건 = 집운 배송 요청 1번 (집운 번호 1개). 고객 주문(MarketOrder) 1건에 붙는다.
    배대지(집운 웨이하이 창고)에 들어온 소포를 한국 고객에게 보내 달라고 요청하고 배송비를 낸 기록 — 출고 · 국제 운송 · 국내 송장까지.
    통관은 받는 사람 1명 단위라 고객 주문마다 따로 요청한다 (같은 고객 여러 소포는 한 요청에 묶을 수 있다).
    바꿀 때마다 그 고객 주문의 추적 기록(OrderEvent jiyun_*)에 이전값 → 새값으로 남는다."""

    order = fields.ForeignKeyField("models.MarketOrder", related_name="jiyun_shipments", on_delete=fields.RESTRICT)
    jiyun_no = fields.CharField(max_length=60)                       # 집운 배송 요청 번호 (物流订单号) — 살아 있는 것끼리 겹치지 않게
    status = fields.CharField(max_length=20, default="requested")     # core/jiyun_config.JIYUN_STATUS
    packages = fields.JSONField(default=list)                        # 묶인 소포 — 중국 운송장 번호들
    weight_kg = fields.DecimalField(max_digits=8, decimal_places=2, null=True)    # 집운이 잰 무게 (요금 무게)
    fee_cny = fields.DecimalField(max_digits=12, decimal_places=2, null=True)     # 집운 배송비 (위안, 화면 표시)
    transport = fields.CharField(max_length=10, null=True)           # sea 해운 · air 항공
    requested_at = fields.DatetimeField(null=True)                   # 배송 요청(결제) 시각

    # 배송비 실제 결제 — 타오바오 구매기록과 같은 칸 (core/purchase_config.PAY_METHOD · CHARGED_STATUS)
    pay_method = fields.CharField(max_length=20, null=True)
    pay_currency = fields.CharField(max_length=3, null=True)
    pay_amount = fields.DecimalField(max_digits=12, decimal_places=2, null=True)  # 결제창 금액 (결제 수수료 포함)
    charged_krw = fields.IntField(null=True)                         # 실제 청구 원화
    charged_status = fields.CharField(max_length=10, default="none")  # none 미확인 · approved 승인 · settled 청구 확정
    charged_at = fields.DatetimeField(null=True)
    charged_source = fields.CharField(max_length=100, null=True)

    # 출고 · 국제 운송 · 국내 송장
    dispatched_at = fields.DatetimeField(null=True)                  # 집운 출고
    hbl = fields.CharField(max_length=60, null=True)                 # 국제 운송장 (House B/L) — UNI-PASS 통관 조회 번호
    kr_courier = fields.CharField(max_length=20, null=True)          # 국내 택배사 — core/shipping_config.COURIERS 키
    kr_tracking_no = fields.CharField(max_length=60, null=True)      # 국내 송장 — 마켓 발송처리에 쓴다

    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField(
        "models.User", related_name="created_jiyun_shipments", null=True, on_delete=fields.SET_NULL
    )
    deleted_at = fields.DatetimeField(null=True)                     # 소프트 삭제 — 추적 기록은 남는다

    class Meta:
        table = "jiyun_shipment"
