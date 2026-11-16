from tortoise import fields

from models.base import BaseModel


class JiyunBundle(BaseModel):
    """집운 묶음 1개 = 집운 물류 주문 1건 (LP 번호 1개) — 받는 사람이 같은 고객 주문 여러 건을 한 상자로 (2026-11-16).

    번호: PRE_LP + 대문자·숫자 10자리 (예: PRE_LP7K3QZ9A1BX). 결제 전 '예약 번호'이고, 집운 결제하면 LP 번호가 붙는다.
    흐름: open(주문이 계속 합류) → confirmed(묶음 확정 · 결제 대기, 합류 잠금) → paid(집운 결제 · LP 번호) → dispatched(출고) → done / cancelled
    주문은 MarketOrder.jiyun_bundle 로 들어온다 (market_order.bundle_key 에도 이 code 를 넣어 예전 화면·점검과 호환).
    집운 결제 기록(JiyunShipment)은 지금처럼 주문마다 1건이고, JiyunShipment.bundle 로 이 묶음에 붙는다."""

    code = fields.CharField(max_length=20, unique=True)              # PRE_LP + 10자리
    receiver_key = fields.CharField(max_length=120, index=True)     # 받는 사람 이름 + 우편번호 (공백 뺌) — 같은 사람만 한 묶음
    is_test = fields.BooleanField(default=False)
    status = fields.CharField(max_length=12, default="open")        # open · confirmed · paid · dispatched · done · cancelled
    lp_no = fields.CharField(max_length=60, null=True)              # 집운 물류 주문번호(LP…) — 결제 기록에서 -2/-3 뗀 번호 1개
    jiyun_trade_id = fields.CharField(max_length=60, null=True)     # 타오바오 집운 결제 주문번호 (tradeId)
    est_weight_g = fields.IntField(null=True)                       # 구성 주문 예상 무게 합 (조사 옵션 용량 × 타오바오 개수 + 상자)
    confirmed_at = fields.DatetimeField(null=True)
    paid_at = fields.DatetimeField(null=True)
    dispatched_at = fields.DatetimeField(null=True)
    memo = fields.TextField(null=True)

    class Meta:
        table = "jiyun_bundle"
