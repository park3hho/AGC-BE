from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from core.import_decl_config import DECL_KIND, DECL_STATUS


def _blank(v):
    if v is None:
        return None
    v = str(v).strip()
    return v or None


class DeclItem(BaseModel):
    name_en: str = Field(max_length=200)          # 제품명 — 영문 대문자·숫자 (브랜드 + 제품 + 용량 + 개수)
    maker_en: Optional[str] = Field(default=None, max_length=100)   # 제조회사명 — 영문 브랜드
    country: str = Field(default="CN", max_length=2)
    qty: int = Field(default=1, ge=1, le=9999)
    unit: str = Field(default="EA", max_length=5)


class _Common(BaseModel):
    decl_no: Optional[str] = Field(default=None, max_length=30)
    receipt_no: Optional[str] = Field(default=None, max_length=40)
    kind: Optional[str] = None
    status: Optional[str] = None
    agency_code: Optional[str] = Field(default=None, max_length=10)
    bl_no: Optional[str] = Field(default=None, max_length=60)
    vessel: Optional[str] = Field(default=None, max_length=60)
    arrival_date: Optional[date] = None
    warehouse_code: Optional[str] = Field(default=None, max_length=20)
    consignee: Optional[str] = Field(default=None, max_length=40)
    items: Optional[list[DeclItem]] = Field(default=None, max_length=30)
    seller_site: Optional[str] = Field(default=None, max_length=300)
    shipper_site: Optional[str] = Field(default=None, max_length=300)
    sent_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    result: Optional[str] = Field(default=None, max_length=2000)
    memo: Optional[str] = Field(default=None, max_length=2000)
    order_ids: Optional[list[int]] = Field(default=None, min_length=1, max_length=20)

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v):
        v = _blank(v)
        if v is not None and v not in DECL_KIND:
            raise ValueError("신고 구분은 pre(사전) · main(본) 중 하나예요.")
        return v

    @field_validator("status")
    @classmethod
    def known_status(cls, v):
        v = _blank(v)
        if v is not None and v not in DECL_STATUS:
            raise ValueError(f"상태는 {', '.join(DECL_STATUS)} 중 하나예요.")
        return v

    @field_validator("decl_no", "receipt_no", "bl_no")
    @classmethod
    def no_space(cls, v):
        v = _blank(v)
        return v.replace(" ", "") if v else v


class DeclCreate(_Common):
    order_ids: list[int] = Field(min_length=1, max_length=20)
    kind: str = "pre"
    status: str = "sent"


class DeclUpdate(_Common):
    pass
