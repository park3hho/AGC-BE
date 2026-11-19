from datetime import date, datetime
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
    vendor_ref: Optional[dict] = None          # 판매자 상품 식별 캐시 (예: 쿠팡 {productId, vendorItemId}) — 보내면 바꾼다


class CompetitorBulk(BaseModel):
    items: list[CompetitorUpsert] = Field(min_length=1, max_length=200)


class WatchUpsert(BaseModel):
    """점검 설정 넣기 — (제품, 판매처, 옵션) 기준, 보낸 칸만 바꾼다. 옵션을 비우면 그 제품 전체."""
    product_id: int = Field(ge=1)
    platform: Literal["coupang", "naver"]
    option_id: Optional[int] = Field(default=None, ge=1)
    query_override: Optional[str] = Field(default=None, max_length=100)
    search_note: Optional[str] = Field(default=None, max_length=200)
    user_note: Optional[str] = Field(default=None, max_length=300)
    needs_user_check: Optional[bool] = None
    skip_until: Optional[date] = None
    skip_days: Optional[int] = Field(default=None, ge=0, le=60)   # skip_until 대신 '오늘부터 N일' (0 = 보류 해제)
    flag_reason: Optional[str] = Field(default=None, max_length=200)   # 보내면 '확인 필요' 표시 (빈 문자열이면 해제)