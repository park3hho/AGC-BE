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
    """옵션 1개의 판매처별 판매가 (원)."""

    pricing = fields.ForeignKeyField("models.ProductPricing", related_name="option_prices", on_delete=fields.CASCADE)
    option = fields.ForeignKeyField("models.PriceSurveyOption", related_name="prices", on_delete=fields.CASCADE)
    sale_price = fields.IntField()

    class Meta:
        table = "option_price"
        unique_together = (("pricing", "option"),)


class ExchangeRate(BaseModel):
    """외부 API 에서 받은 위안 환율 캐시 — 하루 1건. 외부 API 가 죽어도 마지막 값으로 계산한다."""

    date = fields.DateField(unique=True)
    cny_krw = fields.DecimalField(max_digits=12, decimal_places=4)
    source = fields.CharField(max_length=50)                                    # 받은 API 이름

    class Meta:
        table = "exchange_rate"
