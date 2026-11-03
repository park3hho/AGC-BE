from tortoise import fields

from models.base import BaseModel


class DomesticShipment(BaseModel):
    """국내 배송 기록 1건 = 국내 택배 송장 1개 (2026-11-03). 고객 주문(MarketOrder) 1건에 붙는다.
    타오바오 구매기록 → 집운 기록 → 국내 배송 기록. 집운 기록의 국내 송장 · 마켓 원본 송장에서 자동으로 만든다.
    마켓 발송처리(마켓에 등록된 택배사·송장·시각)와 배송 조회(tracker.delivery) 결과를 같이 적는다.
    바꿀 때마다 그 고객 주문의 추적 기록(OrderEvent domestic_*)에 이전값 → 새값으로 남는다."""

    order = fields.ForeignKeyField("models.MarketOrder", related_name="domestic_shipments", on_delete=fields.RESTRICT)
    jiyun = fields.ForeignKeyField(
        "models.JiyunShipment", related_name="domestic_shipments", null=True, on_delete=fields.SET_NULL
    )
    courier = fields.CharField(max_length=20, null=True)             # core/shipping_config.COURIERS 키 (모르면 비움)
    tracking_no = fields.CharField(max_length=60)                    # 국내 송장
    status = fields.CharField(max_length=20, default="ready")         # core/domestic_config.DOMESTIC_STATUS
    source = fields.CharField(max_length=10, default="manual")        # jiyun · market · manual

    # 마켓 발송처리 — 마켓 주문 원본에 보이는 값 (네이버 delivery · 쿠팡 invoiceNumber)
    market_courier = fields.CharField(max_length=30, null=True)      # 마켓에 등록된 택배사 코드 (예: TODAY)
    market_tracking_no = fields.CharField(max_length=60, null=True)
    market_sent_at = fields.DatetimeField(null=True)                 # 발송처리 일시 (네이버 sendDate)
    market_wrong = fields.BooleanField(default=False)                # 네이버 isWrongTrackingNumber

    # 배송 조회 — tracker.delivery
    track_state = fields.CharField(max_length=40, null=True)         # 마지막 단계 이름 (예: 픽업, 배송출발, 배송완료)
    track_state_id = fields.CharField(max_length=30, null=True)      # at_pickup · in_transit · out_for_delivery · delivered …
    track_location = fields.CharField(max_length=100, null=True)
    track_last_at = fields.DatetimeField(null=True)                  # 마지막 단계 시각
    track_events = fields.JSONField(default=list)                    # [{time, status, location, description}] 오래된 것부터
    track_error = fields.CharField(max_length=200, null=True)        # 조회 실패 · 아직 조회 안 됨
    tracked_at = fields.DatetimeField(null=True)                     # 마지막 조회

    delivered_at = fields.DatetimeField(null=True)
    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField(
        "models.User", related_name="created_domestic_shipments", null=True, on_delete=fields.SET_NULL
    )
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "domestic_shipment"
