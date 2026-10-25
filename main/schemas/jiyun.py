from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from core.jiyun_config import JIYUN_STATUS, PACKAGES_MAX
from core.purchase_config import CHARGED_STATUS, PAY_CURRENCY, PAY_METHOD
from core.shipping_config import COURIERS, TRANSPORTS


def _blank(v):
    if v is None:
        return None
    v = v.strip()
    return v or None


def _no_space(v):
    v = _blank(v)
    return v.replace(" ", "") if v else v


class _Common(BaseModel):
    packages: Optional[list[str]] = Field(default=None, max_length=PACKAGES_MAX)
    weight_kg: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("999"), decimal_places=2)
    fee_cny: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("999999"), decimal_places=2)
    transport: Optional[str] = None
    requested_at: Optional[datetime] = None
    pay_method: Optional[str] = None
    pay_currency: Optional[str] = None
    pay_amount: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999999"), decimal_places=2)
    charged_krw: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    charged_status: Optional[str] = None
    charged_at: Optional[datetime] = None
    charged_source: Optional[str] = Field(default=None, max_length=100)
    dispatched_at: Optional[datetime] = None
    hbl: Optional[str] = Field(default=None, max_length=60)
    kr_courier: Optional[str] = None
    kr_tracking_no: Optional[str] = Field(default=None, max_length=60)
    memo: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("packages")
    @classmethod
    def clean_packages(cls, v):
        if v is None:
            return v
        out = [_no_space(x) for x in v]
        return [x for x in dict.fromkeys(out) if x]

    @field_validator("transport")
    @classmethod
    def known_transport(cls, v):
        v = _blank(v)
        if v is not None and v not in TRANSPORTS:
            raise ValueError("운송은 sea(해운) · air(항공) 중 하나예요.")
        return v

    @field_validator("pay_method")
    @classmethod
    def known_method(cls, v):
        v = _blank(v)
        if v is not None and v not in PAY_METHOD:
            raise ValueError(f"결제수단은 {', '.join(PAY_METHOD)} 중 하나예요.")
        return v

    @field_validator("pay_currency")
    @classmethod
    def known_currency(cls, v):
        v = _blank(v)
        if v is not None:
            v = v.upper()
            if v not in PAY_CURRENCY:
                raise ValueError("결제 통화는 USD · KRW · CNY 중 하나예요.")
        return v

    @field_validator("charged_status")
    @classmethod
    def known_charged(cls, v):
        if v is None:
            return "none"
        if v not in CHARGED_STATUS:
            raise ValueError("청구 확인은 none · approved · settled 중 하나예요.")
        return v

    @field_validator("kr_courier")
    @classmethod
    def known_courier(cls, v):
        v = _blank(v)
        if v is not None and v not in COURIERS:
            raise ValueError(f"국내 택배사는 {', '.join(COURIERS)} 중 하나예요.")
        return v

    @field_validator("hbl", "kr_tracking_no")
    @classmethod
    def numbers(cls, v):
        return _no_space(v)

    @field_validator("charged_source", "memo")
    @classmethod
    def blank(cls, v):
        return _blank(v)


def _jiyun_no(v):
    v = _no_space(v)
    if not v:
        raise ValueError("집운 번호를 입력해주세요.")
    return v


class JiyunCreate(_Common):
    order_id: int                                        # 고객 주문 (MarketOrder)
    jiyun_no: str = Field(max_length=60)
    status: str = "requested"

    @field_validator("jiyun_no")
    @classmethod
    def no(cls, v):
        return _jiyun_no(v)

    @field_validator("status")
    @classmethod
    def known_status(cls, v):
        if v not in JIYUN_STATUS:
            raise ValueError("집운 상태가 올바르지 않습니다.")
        return v


class JiyunUpdate(_Common):
    """PATCH — 보낸 필드만 바꾼다. 붙은 고객 주문은 바꾸지 않는다 (잘못 붙였으면 삭제 후 다시)."""

    jiyun_no: Optional[str] = Field(default=None, max_length=60)
    status: Optional[str] = None

    @field_validator("jiyun_no")
    @classmethod
    def no(cls, v):
        return _jiyun_no(v)

    @field_validator("status")
    @classmethod
    def known_status(cls, v):
        if v is None or v not in JIYUN_STATUS:
            raise ValueError("집운 상태가 올바르지 않습니다.")
        return v
