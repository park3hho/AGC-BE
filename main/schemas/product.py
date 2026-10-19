from typing import Optional

from pydantic import BaseModel, Field, field_validator

from schemas.common import check_photo_url, clean_str


class ProductCreate(BaseModel):
    # code 는 BE 가 발급한다 (PR-YYMMDD-XXXX, utils/code_gen.py)
    photo_url: Optional[str] = Field(default=None, max_length=1000)
    title_cn: str = Field(max_length=300)
    title_ko: Optional[str] = Field(default=None, max_length=300)

    @field_validator("title_cn")
    @classmethod
    def validate_title_cn(cls, v):
        v = clean_str(v)
        if not v:
            raise ValueError("중국어 제목을 입력해주세요.")
        return v

    @field_validator("title_ko")
    @classmethod
    def validate_title_ko(cls, v):
        return clean_str(v)

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v):
        return check_photo_url(v)


class ProductUpdate(BaseModel):
    """보낸 필드만 바꾼다 (model_dump(exclude_unset=True)). 코드·추가일은 바꿀 수 없다."""

    photo_url: Optional[str] = Field(default=None, max_length=1000)
    title_cn: Optional[str] = Field(default=None, max_length=300)
    title_ko: Optional[str] = Field(default=None, max_length=300)

    @field_validator("title_cn")
    @classmethod
    def validate_title_cn(cls, v):
        v = clean_str(v)
        if not v:
            raise ValueError("중국어 제목은 비울 수 없습니다.")
        return v

    @field_validator("title_ko")
    @classmethod
    def validate_title_ko(cls, v):
        return clean_str(v)

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v):
        return check_photo_url(v)
