from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


def _blank(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


class AlertIn(BaseModel):
    key: str = Field(min_length=1, max_length=200)
    kind: str = Field(max_length=30)
    title: str = Field(min_length=1, max_length=200)
    body: Optional[str] = Field(default=None, max_length=4000)
    level: str = "info"
    order_codes: list[str] = Field(default_factory=list, max_length=50)
    target: Optional[str] = Field(default=None, max_length=60)
    source: Optional[str] = Field(default=None, max_length=60)


class AlertPatch(BaseModel):
    resolved: bool


class PackageIn(BaseModel):
    tracking_no: str = Field(min_length=1, max_length=60)
    courier: Optional[str] = Field(default=None, max_length=50)
    status: str = "shipped"                      # shipped · arrived · problem
    shipped_at: Optional[datetime] = None
    arrived_at: Optional[datetime] = None
    last_text: Optional[str] = Field(default=None, max_length=200)
    memo: Optional[str] = Field(default=None, max_length=300)

    @field_validator("tracking_no")
    @classmethod
    def no_spaces(cls, v):
        v = (v or "").replace(" ", "").strip()
        if not v:
            raise ValueError("운송장 번호를 입력해주세요.")
        return v

    @field_validator("courier", "last_text", "memo")
    @classmethod
    def blank(cls, v):
        return _blank(v)


class PackagePatch(BaseModel):
    tracking_no: Optional[str] = Field(default=None, max_length=60)
    courier: Optional[str] = Field(default=None, max_length=50)
    status: Optional[str] = None
    shipped_at: Optional[datetime] = None
    arrived_at: Optional[datetime] = None
    last_text: Optional[str] = Field(default=None, max_length=200)
    memo: Optional[str] = Field(default=None, max_length=300)


class OrderMarkIn(BaseModel):
    """30분 점검 상태 표시 — 네이버 발송지연 요청 시각 · 발송기한 알린 단계."""
    delay_requested_at: Optional[datetime] = None
    deadline_stage: Optional[str] = None         # d3 · d1 · over · "" (지우기)


class BundleNoticeIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=300)
    notified_at: Optional[datetime] = None       # 비우면 지금
    clear: bool = False                          # true 면 안내 표시 지우기
