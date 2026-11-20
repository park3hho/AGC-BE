from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class TopupIn(BaseModel):
    topped_at: datetime
    cny: Decimal = Field(gt=0, le=Decimal("9999999"), decimal_places=2)
    krw: int = Field(gt=0, le=1_000_000_000)
    is_opening: bool = False
    memo: Optional[str] = Field(default=None, max_length=200)


class TopupPatch(BaseModel):
    topped_at: Optional[datetime] = None
    cny: Optional[Decimal] = Field(default=None, gt=0, le=Decimal("9999999"), decimal_places=2)
    krw: Optional[int] = Field(default=None, gt=0, le=1_000_000_000)
    is_opening: Optional[bool] = None
    memo: Optional[str] = Field(default=None, max_length=200)


class SpendIn(BaseModel):
    spent_at: datetime
    cny: Decimal = Field(gt=0, le=Decimal("9999999"), decimal_places=2)
    memo: str = Field(min_length=1, max_length=200)
