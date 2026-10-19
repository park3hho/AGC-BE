from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from core.pricing_config import DEFAULT_FX_MARKUP_PCT

INT32_MAX = 2_147_483_647   # DB IntField(int4) 한계 — 넘으면 DB 오류(500)가 나므로 스키마에서 막는다


class OptionPriceIn(BaseModel):
    option_id: int
    sale_price: int = Field(ge=1, le=INT32_MAX)                              # 판매가 (원)


class ExchangeRateSave(BaseModel):
    """PUT /exchange-rate — 오늘 환율 직접 입력."""

    cny_krw: Decimal = Field(gt=0, le=10000, max_digits=12, decimal_places=4)            # 원/위안


class PricingSave(BaseModel):
    """PUT /products/{product_id}/pricing/{platform} — 그 판매처 설정 + 옵션 판매가 통째로 교체.
    Decimal 필드는 문자열("10.8")·숫자(10.8) 둘 다 받는다.
    옵션 중복 · 다른 조사 옵션은 contract 상 400 이라 여기(422)가 아니라 서비스에서 막는다."""

    survey_id: int
    fx_rate: Decimal = Field(gt=0, max_digits=12, decimal_places=4)                      # 저장 시점 환율 (원/위안) — 기록용
    fx_markup_pct: Decimal = Field(default=Decimal(DEFAULT_FX_MARKUP_PCT), ge=0, le=100, max_digits=5, decimal_places=2)
    # 배송비 (원) — 더 이상 쓰지 않는다 (옵션별 무게로 계산). 예전 FE 가 보내도 받아서 저장만 한다
    shipping_fee: Optional[int] = Field(default=None, ge=0, le=INT32_MAX)
    platform_fee_rate: Decimal = Field(ge=0, le=100, max_digits=5, decimal_places=2)     # 플랫폼 수수료 %
    payment_fee_rate: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2)
    option_prices: list[OptionPriceIn]                                                   # 빠진 옵션 = 판매가 없음
    # 대표 옵션 (네이버 추가금 0원) — option_prices 에 판매가가 있는 옵션이어야 한다. null = 자동
    base_option_id: Optional[int] = None
