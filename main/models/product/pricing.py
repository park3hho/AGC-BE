from tortoise import fields

from core.pricing_config import DEFAULT_FX_MARKUP_PCT, DEFAULT_FX_RATE, DEFAULT_SHIPPING_FEE, Platform
from models.base import BaseModel


class ProductPricing(BaseModel):
    """제품 1개의 판매처별 가격 설정. 제품 1 : 판매처별 1개.
    차익·마진율은 저장하지 않고 판매가 · 원가 · 수수료로 계산한다."""

    product = fields.ForeignKeyField("models.Product", related_name="pricings", on_delete=fields.CASCADE)
    survey = fields.ForeignKeyField("models.PriceSurvey", related_name="pricings")  # 기준으로 쓴 가격 조사
    platform = fields.CharEnumField(Platform, max_length=20)

    # 환율 — 가격을 정한 시점 값으로 고정 (나중에 환율이 바뀌면 차익 변화를 비교할 수 있게)
    fx_rate = fields.DecimalField(max_digits=12, decimal_places=4, default=DEFAULT_FX_RATE)  # 고시 환율 (원/위안)
    fx_date = fields.DateField(null=True)                                       # 그 환율의 기준일 — 고정값이면 없음
    fx_markup_pct = fields.DecimalField(max_digits=5, decimal_places=2, default=DEFAULT_FX_MARKUP_PCT)  # 실결제 가산율 %

    shipping_fee = fields.IntField(default=DEFAULT_SHIPPING_FEE)                # 배송비 (원/개)
    platform_fee_rate = fields.DecimalField(max_digits=5, decimal_places=2)     # 플랫폼 수수료 %
    payment_fee_rate = fields.DecimalField(max_digits=5, decimal_places=2, default=0)  # 결제 수수료 %

    # 대표 옵션 — 네이버처럼 "대표가 + 옵션 추가금"으로 등록하는 판매처에서 추가금 0원인 옵션.
    # 비어 있으면 자동 (FE 가 추가금 한도를 만족하는 옵션을 고른다). 옵션이 지워지면 비운다
    base_option = fields.ForeignKeyField(
        "models.PriceSurveyOption", related_name="base_of_pricings", null=True, on_delete=fields.SET_NULL
    )

    class Meta:
        table = "product_pricing"
        unique_together = (("product", "platform"),)


class OptionPrice(BaseModel):
    """판매 옵션 1개의 판매처별 판매가 (원). 판매 옵션 = 가격 조사 옵션 × 묶음 수.
    묶음 수 1 = 조사 옵션 그대로. 2 이상 = 그 옵션을 N개 묶어 한 상품으로 판다 (core/shipping_config 묶음 판매)."""

    pricing = fields.ForeignKeyField("models.ProductPricing", related_name="option_prices", on_delete=fields.CASCADE)
    option = fields.ForeignKeyField("models.PriceSurveyOption", related_name="prices", on_delete=fields.CASCADE)
    bundle_qty = fields.SmallIntField(default=1)     # 묶음 수 — 타오바오에서 이 옵션을 몇 개 사서 한 상품으로 파는지
    sale_price = fields.IntField()

    # 네이버처럼 "대표가 + 추가금" 판매처에서 추가금 한도를 넘는 옵션을 상품 여러 개로 나눠 등록할 때의 직접 지정값.
    # 자동 묶음(용량·입수별 → 가격)은 FE utils/pricing.naverListingPlan 이 계산하고, 여기엔 사람이 바꾼 것만 남는다.
    listing_group = fields.SmallIntField(null=True)   # 이 옵션을 넣을 상품 번호 (1부터) · null = 자동
    is_base = fields.BooleanField(default=False)      # 그 상품의 대표 옵션(추가금 0원)으로 직접 지정

    class Meta:
        table = "option_price"
        unique_together = (("pricing", "option", "bundle_qty"),)


class ExchangeRate(BaseModel):
    """외부 API 에서 받은 위안 환율 캐시 — 하루 1건. 외부 API 가 죽어도 마지막 값으로 계산한다."""

    date = fields.DateField(unique=True)
    cny_krw = fields.DecimalField(max_digits=12, decimal_places=4)
    source = fields.CharField(max_length=50)                                    # 받은 API 이름

    class Meta:
        table = "exchange_rate"


class ExchangeRateLog(BaseModel):
    """서버가 저장한 환율 기록 — 매시간 자동 · 지금 받아오기 · 직접 입력마다 한 줄씩 쌓는다 (추이 그래프).
    저장 시각 = created_at. 계산에 쓰는 값은 exchange_rate(하루 1건)이고, 이 표는 기록만."""

    cny_krw = fields.DecimalField(max_digits=12, decimal_places=4)
    source = fields.CharField(max_length=50)                                    # hana · open_er_api · manual
    observed_at = fields.CharField(max_length=40, null=True)                    # 출처가 알려준 기준 시각 (문자열 그대로)

    class Meta:
        table = "exchange_rate_log"


class ProductBundle(BaseModel):
    """판매 옵션으로 채택한 묶음 (조사 옵션 × N) — 판매가와 따로 남긴다 (2026-10-26).
    판매가는 사람이 가격 책정에서 정하므로, 채택만 하고 판매가가 빈 묶음이 있을 수 있다.
    빼면 deleted_at 을 채운다 (기록은 남긴다). 다시 넣으면 같은 줄을 살린다."""

    product = fields.ForeignKeyField("models.Product", related_name="bundles", on_delete=fields.CASCADE)
    option = fields.ForeignKeyField("models.PriceSurveyOption", related_name="bundles", on_delete=fields.CASCADE)
    bundle_qty = fields.SmallIntField()
    source = fields.CharField(max_length=10, default="manual")    # rule(10kg 제안 일괄) · manual(화면에서 추가)
    created_by = fields.ForeignKeyField("models.User", related_name="created_bundles", null=True,
                                        on_delete=fields.SET_NULL)
    deleted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "product_bundle"
        unique_together = (("option", "bundle_qty"),)