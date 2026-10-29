from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from core.pricing_config import Platform
from schemas.common import _clean_url


def _blank(v):
    if v is None:
        return None
    v = v.strip()
    return v or None


class _Common(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    url: Optional[str] = Field(default=None, max_length=1000)
    listed_at: Optional[datetime] = None          # 업로드 일시 (+09:00 붙여 보내면 KST)
    memo: Optional[str] = Field(default=None, max_length=500)

    @field_validator("title", "memo")
    @classmethod
    def blank(cls, v):
        return _blank(v)

    @field_validator("url")
    @classmethod
    def clean_url(cls, v):
        try:
            return _clean_url(v)
        except ValueError:
            raise ValueError("상품 링크를 확인해주세요 (예: https://www.coupang.com/vp/products/…).") from None


class ListingCreate(_Common):
    product_id: int = Field(ge=1)
    platform: Platform
    market_product_id: str = Field(max_length=50)

    @field_validator("market_product_id")
    @classmethod
    def required(cls, v):
        v = (v or "").strip().replace(" ", "")
        if not v:
            raise ValueError("마켓 상품번호를 입력해주세요.")
        return v


class ListingUpdate(_Common):
    """보낸 칸만 바꾼다 (판매처 · 상품번호는 못 바꿈 — 틀렸으면 지우고 다시 추가)."""
