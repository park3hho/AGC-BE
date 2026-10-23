from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core.company_info_config import DETAILS_MAX, INFO_LINK_KEYS
from schemas.company_account import _clean_url, _required_text


class DetailIn(BaseModel):
    label: str = Field(max_length=50)
    value: str = Field(max_length=500)

    @field_validator("label", "value")
    @classmethod
    def required(cls, v):
        return _required_text(v)


def _blank_to_none(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    return v.strip() or None


class _Common(BaseModel):
    value: Optional[str] = Field(default=None, max_length=500)
    details: list[DetailIn] = Field(default_factory=list)
    issuer: Optional[str] = Field(default=None, max_length=100)
    issued_on: Optional[date] = None
    expires_on: Optional[date] = None
    remind: bool = True
    url: Optional[str] = Field(default=None, max_length=508)
    link: Optional[str] = Field(default=None, max_length=50)
    sort: int = Field(default=0, ge=-999, le=999)
    memo: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("value", "issuer", "memo")
    @classmethod
    def blank(cls, v):
        return _blank_to_none(v)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        return _clean_url(v)

    @field_validator("link")
    @classmethod
    def validate_link(cls, v):
        v = _blank_to_none(v)
        if v is not None and v not in INFO_LINK_KEYS:
            raise ValueError("앱 연결 값이 올바르지 않습니다.")
        return v

    @field_validator("details")
    @classmethod
    def validate_details(cls, v):
        v = v or []
        labels = [d.label for d in v]
        if len(labels) != len(set(labels)):
            raise ValueError("세부 값 이름이 겹칩니다.")
        if len(v) > DETAILS_MAX:
            raise ValueError(f"세부 값은 {DETAILS_MAX}개까지 넣을 수 있습니다.")
        return v

    @model_validator(mode="after")
    def check_dates(self):
        if self.issued_on and self.expires_on and self.issued_on > self.expires_on:
            raise ValueError("만료일이 발급일보다 빠릅니다.")
        return self


class CompanyInfoCreate(_Common):
    category: str = Field(max_length=30)
    name: str = Field(max_length=100)

    @field_validator("category", "name")
    @classmethod
    def required(cls, v):
        return _required_text(v)


class CompanyInfoUpdate(_Common):
    """PATCH — 보낸 필드만 바꾼다."""

    category: Optional[str] = Field(default=None, max_length=30)
    name: Optional[str] = Field(default=None, max_length=100)
    remind: Optional[bool] = None
    sort: Optional[int] = Field(default=None, ge=-999, le=999)

    @field_validator("category", "name")
    @classmethod
    def required(cls, v):
        if v is None:
            raise ValueError("값을 입력해주세요.")
        return _required_text(v)

    @field_validator("remind", "sort")
    @classmethod
    def not_null(cls, v):
        if v is None:
            raise ValueError("값을 입력해주세요.")
        return v
