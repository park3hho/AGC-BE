from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from schemas.common import check_photo_url, check_url, clean_str


class PriceSurveyOptionIn(BaseModel):
    option1: str = Field(max_length=200)
    option2: Optional[str] = Field(default=None, max_length=200)
    price_cny: Decimal = Field(gt=0, max_digits=12, decimal_places=2)

    @field_validator("option1")
    @classmethod
    def validate_option1(cls, v):
        v = clean_str(v)
        if not v:
            raise ValueError("옵션1을 입력해주세요.")
        return v

    @field_validator("option2")
    @classmethod
    def validate_option2(cls, v):
        return clean_str(v)


class PriceSurveyCreate(BaseModel):
    product_code: str = Field(max_length=50)
    # code 는 BE 가 조사일 기준으로 발급한다 (RS-YYMMDD-XXXX, utils/code_gen.py)
    survey_date: date
    photo_url: Optional[str] = Field(default=None, max_length=1000)
    taobao_url: str = Field(max_length=1000)
    coupang_min_price: Optional[int] = Field(default=None, ge=0)
    coupang_url: Optional[str] = Field(default=None, max_length=1000)
    naver_min_price: Optional[int] = Field(default=None, ge=0)
    naver_url: Optional[str] = Field(default=None, max_length=1000)
    options: list[PriceSurveyOptionIn] = Field(min_length=1)

    @field_validator("product_code")
    @classmethod
    def validate_product_code(cls, v):
        v = clean_str(v)
        if not v:
            raise ValueError("제품 코드를 입력해주세요.")
        return v

    @field_validator("taobao_url")
    @classmethod
    def validate_taobao_url(cls, v):
        v = check_url(v)
        if not v:
            raise ValueError("타오바오 링크를 입력해주세요.")
        return v

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v):
        return check_photo_url(v)

    @field_validator("coupang_url", "naver_url")
    @classmethod
    def validate_urls(cls, v):
        return check_url(v)

    @model_validator(mode="after")
    def check_duplicate_options(self):
        seen = set()
        for o in self.options:
            key = (o.option1, o.option2)
            if key in seen:
                raise ValueError(f"같은 옵션이 두 번 들어 있습니다: {o.option1} / {o.option2 or '-'}")
            seen.add(key)
        return self
