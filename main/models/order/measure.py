from tortoise import fields

from models.base import BaseModel


class OptionMeasure(BaseModel):
    """실측 1건 = 실제로 보낸 상자 하나를 집운 창고가 잰 무게 · 크기 (2026-11-18).

    주문이 들어와 집운으로 보낼 때마다, 그 상자의 실제 무게(kg)와 가로 · 세로 · 높이(cm)를 상품 옵션별로 쌓는다.
    같은 옵션 × 같은 묶음 수(units)의 실측이 쌓이면 평균을 내서, 가격 책정 배송비 계산이 옵션 이름으로 추정한 무게 대신 이 값을 먼저 쓴다.

    - units = 묶음 수 × 주문 수량 (15병 옵션 x2 묶음을 1개 주문 → 2). 한 상자에 든 조사 옵션 개수.
    - mixed = 여러 옵션 · 여러 주문을 한 상자로 합포장해 옵션별로 나눌 수 없는 상자. 기록은 남기되 평균에서 뺀다.
    - 비공개: 원가 · 운임 구조라 AGC 로그인(가격 책정 권한) 뒤에서만 읽는다. 자사몰 · 마켓 등록 데이터로 내보내지 않는다."""

    product_id = fields.IntField(null=True, index=True)
    option_id = fields.IntField(null=True, index=True)               # 제품 옵션 id (product_option.id)
    sku = fields.CharField(max_length=60, null=True, index=True)    # 주문 판매자 상품코드 그대로 PR-yymmdd-xxxx-{옵션}x{묶음}
    units = fields.IntField(default=1)                               # 상자 안 조사 옵션 개수 = 묶음 수 × 주문 수량
    mixed = fields.BooleanField(default=False)                       # 합포장 — 옵션별로 못 나눔, 평균에서 뺌

    order = fields.ForeignKeyField("models.MarketOrder", related_name="measures", null=True, on_delete=fields.SET_NULL)
    jiyun = fields.ForeignKeyField("models.JiyunShipment", related_name="measures", null=True, on_delete=fields.SET_NULL)
    jiyun_no = fields.CharField(max_length=60, null=True)

    weight_kg = fields.DecimalField(max_digits=8, decimal_places=3, null=True)    # 실제 무게
    length_cm = fields.DecimalField(max_digits=6, decimal_places=1, null=True)    # 가로
    width_cm = fields.DecimalField(max_digits=6, decimal_places=1, null=True)     # 세로(폭)
    height_cm = fields.DecimalField(max_digits=6, decimal_places=1, null=True)    # 높이

    source = fields.CharField(max_length=20, default="jiyun")        # jiyun 집운 창고 · manual 직접 · backfill 예전 집운 기록(무게만)
    measured_at = fields.DatetimeField(null=True)
    memo = fields.TextField(null=True)
    created_by = fields.ForeignKeyField("models.User", related_name="created_measures", null=True, on_delete=fields.SET_NULL)
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "option_measure"
        table_description = "옵션별 실측 — 실제 보낸 상자의 무게·가로·세로·높이 (집운 창고), 배송비 계산용, 비공개 (2026-11-18)"
