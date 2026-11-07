from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CompetitorUpsert(BaseModel):
    """최저가 경쟁 확인 결과 넣기 — 같은 (제품, 판매처, 옵션)이면 덮어쓴다."""
    product_id: int = Field(ge=1)
    platform: Literal["coupang", "naver"]
    option_id: Optional[int] = Field(default=None, ge=1)
    status: Literal["found", "only_us", "not_found"] = "found"
    vendor_name: Optional[str] = Field(default=None, max_length=100)
    vendor_price: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    vendor_shipping: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    vendor_type: Optional[Literal["agency", "warehouse", "unknown"]] = None
    vendor_note: Optional[str] = Field(default=None, max_length=200)
    vendor_url: Optional[str] = Field(default=None, max_length=500)
    query: Optional[str] = Field(default=None, max_length=100)
    checked_at: Optional[datetime] = None


class CompetitorBulk(BaseModel):
    items: list[CompetitorUpsert] = Field(min_length=1, max_length=200)
