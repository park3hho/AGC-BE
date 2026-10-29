from tortoise import fields

from models.base import BaseModel


class MarketOrder(BaseModel):
    """마켓(네이버·쿠팡) 주문 1줄 = 상품 주문 1개.
    네이버: 상품주문번호(productOrderId) 1개 · 쿠팡: 묶음배송번호(shipmentBoxId) 안의 옵션(vendorItemId) 1개.
    개인정보(전화번호·주소·통관부호)와 마켓 원본 응답은 Fernet 암호문으로만 둔다 — 목록·로그에는 가린 값만."""

    code = fields.CharField(max_length=20, unique=True, null=True)  # 자사 주문 코드 OR-YYMMDD-XXXX (날짜 = 주문일 KST) — 수집할 때 발급
    market = fields.CharField(max_length=10)                       # naver · coupang · shop(자사몰, 2026-10-29)
    line_no = fields.CharField(max_length=60)                       # 마켓 안에서 유일한 줄 번호 (네이버 productOrderId · 쿠팡 shipmentBoxId-vendorItemId)
    order_no = fields.CharField(max_length=40)                      # 마켓 주문번호 (네이버 orderId · 쿠팡 orderId)
    ship_unit_no = fields.CharField(max_length=40)                  # 마켓에 처리(발주확인·발송)를 보낼 단위 (네이버 productOrderId · 쿠팡 shipmentBoxId)
    market_status = fields.CharField(max_length=40)                 # 마켓 원래 상태 (네이버 PAYED… · 쿠팡 ACCEPT…)
    confirmed = fields.BooleanField(default=False)                  # 마켓에 발주확인됨 (네이버 placeOrderStatus=OK · 쿠팡 INSTRUCT 이후)
    stage = fields.CharField(max_length=20, default="received")     # AGC 큰 단계 received(접수) · processing(처리) · done(완료) · cancelled(취소)
    ordered_at = fields.DatetimeField(null=True)
    paid_at = fields.DatetimeField(null=True)
    ship_due_at = fields.DatetimeField(null=True)                   # 마켓 발송 기한 (있으면)

    product_name = fields.CharField(max_length=300)
    option_name = fields.CharField(max_length=300, null=True)
    seller_code = fields.CharField(max_length=100, null=True)       # 판매자 관리코드 — 나중에 AGC 제품·옵션과 연결
    market_product_id = fields.CharField(max_length=40, null=True)  # 네이버 productId · 쿠팡 sellerProductId
    market_option_id = fields.CharField(max_length=40, null=True)   # 네이버 optionManageCode · 쿠팡 vendorItemId
    quantity = fields.IntField(default=1)
    unit_price = fields.IntField(null=True)                         # 원
    total_price = fields.IntField(null=True)                        # 고객 결제 금액 (원)

    receiver_name = fields.CharField(max_length=100, null=True)
    receiver_phone_enc = fields.TextField(null=True)                # 통관용 전화번호 (쿠팡 overseaShippingInfoDto.ordererPhoneNumber · 네이버 shippingAddress.tel1) — 통관부호 검증에 씀
    contact_phone_enc = fields.TextField(null=True)                 # 쇼핑몰 연락처 (쿠팡 receiver.receiverNumber → 없으면 안심번호 safeNumber · 네이버 tel1) — 통관용과 따로 둔다
    receiver_zip = fields.CharField(max_length=10, null=True)
    receiver_address_enc = fields.TextField(null=True)
    pccc_enc = fields.TextField(null=True)                          # 개인통관고유부호 (P…) 또는 일회용 부호 (O…)

    # 통관부호 검증 (UNI-PASS API028) — 최근 결과. 매번의 요청·응답은 OrderEvent(kind=pccc_check)에 남는다
    pccc_status = fields.CharField(max_length=20, default="pending")  # pending · ok · mismatch · missing · error
    pccc_message = fields.TextField(null=True)
    pccc_checked_at = fields.DatetimeField(null=True)
    pccc_valid_to = fields.DateField(null=True)                     # 통관부호 유효기간 만료일
    receiver_hash = fields.CharField(max_length=64, null=True)      # 통관부호·이름·전화·우편번호 지문 — 바뀌면 다시 검증

    raw_enc = fields.TextField(null=True)                           # 마지막으로 받은 마켓 원본 응답 (암호문) — 추적용
    last_synced_at = fields.DatetimeField(null=True)

    # 클레임 (취소·반품·교환 요청) — 2026-10-27. 네이버: productOrder.claimType·claimStatus · 쿠팡: 반품/취소 요청 목록(returnRequests)의 receiptType·receiptStatus
    claim_type = fields.CharField(max_length=20, null=True)        # CANCEL · RETURN · EXCHANGE · ADMIN_CANCEL …
    claim_status = fields.CharField(max_length=40, null=True)      # 마켓 원래 값 (네이버 CANCEL_REQUEST… · 쿠팡 RU·UC·CANCEL…)
    claim_at = fields.DatetimeField(null=True)                     # 클레임 접수 시각
    claim_reason = fields.CharField(max_length=300, null=True)     # 사람이 읽는 사유 — 예: 판매자 취소 · 재고연동오류 (2026-10-27)
    # 실제 정산액 (원) — 쿠팡 매출내역(revenue-history, 구매확정 뒤 생김). 없으면 화면은 수수료율로 추정 (2026-10-27)
    settlement_actual = fields.IntField(null=True)
    settlement_date = fields.DateField(null=True)                   # 정산(예정)일

    class Meta:
        table = "market_order"
        unique_together = (("market", "line_no"),)


class OrderEvent(BaseModel):
    """주문 추적 기록 — 누가(시스템·에이전트·사람) 무엇을 했고 어떤 값을 보내고 받았는지. 지우지도 고치지도 않는다.
    data 에는 개인정보를 가린 값만 넣는다 (원문은 MarketOrder 의 암호문)."""

    order = fields.ForeignKeyField("models.MarketOrder", related_name="events", null=True, on_delete=fields.RESTRICT)
    sync_run = fields.ForeignKeyField("models.OrderSyncRun", related_name="events", null=True, on_delete=fields.SET_NULL)
    actor_type = fields.CharField(max_length=10)                    # system · agent · user
    actor_user = fields.ForeignKeyField("models.User", related_name="order_events", null=True, on_delete=fields.SET_NULL)
    via = fields.CharField(max_length=20)                           # poller · manual · api_key · session
    kind = fields.CharField(max_length=30)                          # collected · changed · pccc_check · …
    summary = fields.CharField(max_length=300)
    data = fields.JSONField(default=dict)

    class Meta:
        table = "order_event"


class OrderSyncRun(BaseModel):
    """주문 수집 1번 — 언제 누가(폴링·수동) 어느 구간을 받아 몇 건이 새로 들어오고 바뀌었는지."""

    market = fields.CharField(max_length=10)
    trigger = fields.CharField(max_length=20)                       # poller · manual
    actor_user = fields.ForeignKeyField("models.User", related_name="order_sync_runs", null=True, on_delete=fields.SET_NULL)
    range_from = fields.DatetimeField()
    range_to = fields.DatetimeField()
    finished_at = fields.DatetimeField(null=True)
    fetched = fields.IntField(default=0)                            # 마켓에서 받은 줄 수
    created = fields.IntField(default=0)
    changed = fields.IntField(default=0)
    checked = fields.IntField(default=0)                            # 통관부호 검증 호출 수
    ok = fields.BooleanField(null=True)                             # 끝까지 성공했는지 (진행 중 null)
    error = fields.TextField(null=True)

    class Meta:
        table = "order_sync_run"
