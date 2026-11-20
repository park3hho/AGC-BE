from tortoise import fields

from models.base import BaseModel


class AlipayTopup(BaseModel):
    """알리페이(즈푸바오) 잔액 충전 한 번 — 위안을 얼마에 샀는지 (2026-11-20 사용자: 선입선출 환율 계산).

    잔액 결제는 오래된 충전부터 깎고(선입선출), 원화는 깎은 충전의 환율로 계산한다.
    is_opening = 장부 시작 때 남아 있던 잔액(기초 잔액). 이보다 앞선 결제는 장부에 넣지 않는다."""

    topped_at = fields.DatetimeField()                               # 충전 시각
    cny = fields.DecimalField(max_digits=12, decimal_places=2)       # 충전된 위안
    krw = fields.IntField()                                          # 낸 원화 (수수료 포함 실제 출금액)
    is_opening = fields.BooleanField(default=False)
    memo = fields.CharField(max_length=200, null=True)
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "alipay_topup"


class AlipaySpend(BaseModel):
    """잔액에서 나간 결제 한 건 — 타오바오 구매 · 집운 운임은 기록에서 자동으로, 그 밖은 직접.
    allocations = 어느 충전에서 몇 위안을 얼마(환율)로 깎았는지 (선입선출 재계산 때마다 다시 씀)."""

    spent_at = fields.DatetimeField()
    cny = fields.DecimalField(max_digits=12, decimal_places=2)
    kind = fields.CharField(max_length=12)                           # purchase · jiyun · other
    ref_id = fields.IntField(null=True)                              # 구매 id · 집운 기록 id
    krw = fields.IntField(null=True)                                 # 선입선출로 계산한 원화
    allocations = fields.JSONField(default=list)                     # [{topup_id, cny, rate, krw}]
    short_cny = fields.DecimalField(max_digits=12, decimal_places=2, default=0)   # 충전 기록이 모자라 임시 환율로 계산한 위안
    memo = fields.CharField(max_length=200, null=True)
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "alipay_spend"
