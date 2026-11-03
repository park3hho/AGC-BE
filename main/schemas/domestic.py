from typing import Optional

from pydantic import BaseModel, Field, field_validator

from core.domestic_config import DOMESTIC_STATUS
from core.shipping_config import COURIERS


def _no_space(v):
    if v is None:
        return None
    v = v.strip().replace(" ", "").replace("-", "")
    return v or None


def _courier(v):
    if v in (None, ""):
        return None
    if v not in COURIERS:
        raise ValueError(f"택배사는 {', '.join(COURIERS)} 중 하나예요.")
    return v


class DomesticCreate(BaseModel):
    order_id: int = Field(ge=1)
    courier: Optional[str] = None
    tracking_no: str = Field(min_length=4, max_length=60)
    memo: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("courier")
    @classmethod
    def _c(cls, v):
        return _courier(v)

    @field_validator("tracking_no")
    @classmethod
    def _t(cls, v):
        return _no_space(v)


class DomesticUpdate(BaseModel):
    courier: Optional[str] = None
    tracking_no: Optional[str] = Field(default=None, min_length=4, max_length=60)
    status: Optional[str] = None
    memo: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("courier")
    @classmethod
    def _c(cls, v):
        return _courier(v)

    @field_validator("tracking_no")
    @classmethod
    def _t(cls, v):
        return _no_space(v)

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in DOMESTIC_STATUS:
            raise ValueError("상태가 올바르지 않습니다.")
        return v
