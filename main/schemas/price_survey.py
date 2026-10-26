from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from schemas.common import check_photo_url, check_url, clean_str


class PriceSurveyOptionIn(BaseModel):
    option1: str = Field(max_length=200)
    option2: Optional[str] = Field(default=None, max_length=200)
    price_cny: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    photo_url: Optional[str] = Field(default=None, max_length=1000)     # 옵션별 사진 (예: 맛별 사진)

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

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v):
        return check_photo_url(v)


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
        _check_duplicate_options(self.options)
        return self


def _check_duplicate_options(options) -> None:
    seen = set()
    for o in options:
        key = (o.option1, o.option2)
        if key in seen:
            raise ValueError(f"같은 옵션이 두 번 들어 있습니다: {o.option1} / {o.option2 or '-'}")
        seen.add(key)


class PriceSurveyUpdate(BaseModel):
    """보낸 필드만 바꾼다 (model_dump(exclude_unset=True)).
    survey_date · product_code 는 조사 코드번호와 묶여 있어 바꿀 수 없다.
    ⚠️ options 를 보내면 전체 교체 — 옵션 행을 지우고 새 id 로 다시 만든다. 그 옵션에 저장된 판매가(option_price)가
    CASCADE 로 지워지고 마켓 등록(listing items.option_id)과도 끊긴다. 이름·사진만 고칠 때는
    PATCH /price-surveys/{id}/options/{option_id} (PriceSurveyOptionPatch) 를 쓴다."""

    photo_url: Optional[str] = Field(default=None, max_length=1000)
    taobao_url: Optional[str] = Field(default=None, max_length=1000)
    coupang_min_price: Optional[int] = Field(default=None, ge=0)
    coupang_url: Optional[str] = Field(default=None, max_length=1000)
    naver_min_price: Optional[int] = Field(default=None, ge=0)
    naver_url: Optional[str] = Field(default=None, max_length=1000)
    options: Optional[list[PriceSurveyOptionIn]] = Field(default=None, min_length=1)

    @field_validator("taobao_url")
    @classmethod
    def validate_taobao_url(cls, v):
        v = check_url(v)
        if not v:
            raise ValueError("타오바오 링크는 비울 수 없습니다.")
        return v

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v):
        return check_photo_url(v)

    @field_validator("coupang_url", "naver_url")
    @classmethod
    def validate_urls(cls, v):
        return check_url(v)

    @field_validator("options")
    @classmethod
    def validate_options(cls, v):
        if v is None:
            raise ValueError("옵션은 비울 수 없습니다.")
        _check_duplicate_options(v)
        return v

class PriceSurveyOptionPatch(BaseModel):
    """옵션 1개를 그 자리에서 고친다 (id 유지 → 저장된 판매가·마켓 등록 연결이 그대로 남는다).
    price_cny 는 여기서 바꾸지 않는다 (가격이 바뀌면 판매가 재계산이 필요하므로 별도 작업)."""

    option1: Optional[str] = Field(default=None, max_length=200)
    option2: Optional[str] = Field(default=None, max_length=200)
    photo_url: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("option1")
    @classmethod
    def validate_option1(cls, v):
        v = clean_str(v)
        if not v:
            raise ValueError("옵션1은 비울 수 없습니다.")
        return v

    @field_validator("option2")
    @classmethod
    def validate_option2(cls, v):
        return clean_str(v)

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v):
        return check_photo_url(v)
