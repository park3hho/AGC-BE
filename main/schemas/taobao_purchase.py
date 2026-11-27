from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from core.purchase_config import CHARGED_STATUS, CN_STATUS, PAY_CURRENCY, PAY_METHOD, PURCHASE_ITEMS_MAX, REFUND_STATUS
from schemas.common import _clean_url


class PurchaseItemIn(BaseModel):
    name: str = Field(max_length=200)                   # 옵션 (맛·용량 등)
    qty: int = Field(ge=1, le=9999)
    price_cny: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("999999"), decimal_places=2)

    @field_validator("name")
    @classmethod
    def required(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("옵션 이름을 입력해주세요.")
        return v


def _blank(v):
    if v is None:
        return None
    v = v.strip()
    return v or None


def _order_no(v):
    v = _blank(v)
    if not v:
        raise ValueError("타오바오 주문번호를 입력해주세요.")
    return v.replace(" ", "")


class _Common(BaseModel):
    shop_name: Optional[str] = Field(default=None, max_length=200)
    item_url: Optional[str] = Field(default=None, max_length=508)
    items: list[PurchaseItemIn] = Field(default_factory=list, max_length=PURCHASE_ITEMS_MAX)
    paid_cny: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("9999999"), decimal_places=2)
    # 할인 줄 [{name, cny, multi}] — 수량 조건 할인은 multi=true (매입가 계산에서 되돌려 더함). 비우면 모름, [] 이면 할인 없음
    discounts: Optional[list[dict]] = Field(default=None, max_length=20)

    @field_validator("discounts")
    @classmethod
    def clean_discounts(cls, v):
        if v is None:
            return None
        out = []
        for d in v:
            try:
                cny = round(abs(float(d.get("cny") or 0)), 2)
            except (TypeError, ValueError):
                raise ValueError("할인 금액(cny)은 숫자로 넣어 주세요.")
            out.append({"name": str(d.get("name") or "")[:60], "cny": cny, "multi": bool(d.get("multi"))})
        return out
    purchased_at: Optional[datetime] = None
    pay_method: Optional[str] = None                                    # core/purchase_config.PAY_METHOD
    pay_currency: Optional[str] = None                                  # USD · KRW · CNY
    pay_amount: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("99999999"), decimal_places=2)
    charged_krw: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    charged_status: Optional[str] = None                                # none · approved · settled
    charged_at: Optional[datetime] = None
    charged_source: Optional[str] = Field(default=None, max_length=100)
    cn_status: str = "ordered"
    shipped_at: Optional[datetime] = None
    cn_courier: Optional[str] = Field(default=None, max_length=50)
    cn_tracking_no: Optional[str] = Field(default=None, max_length=60)
    arrived_at: Optional[datetime] = None
    memo: Optional[str] = Field(default=None, max_length=2000)
    # 30분 점검 상태 (2026-11-19) — 메모 태그 대신
    cn_last_text: Optional[str] = Field(default=None, max_length=200)   # 마지막 물류 문구
    package_count: Optional[int] = Field(default=None, ge=1, le=50)     # 판매처가 말한 소포 수
    refund_status: Optional[str] = None                                 # none · requested · success · rejected
    refund_no: Optional[str] = Field(default=None, max_length=40)
    refund_cny: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("9999999"), decimal_places=2)
    refund_requested_at: Optional[datetime] = None
    refund_done_at: Optional[datetime] = None

    @field_validator("refund_status")
    @classmethod
    def known_refund(cls, v):
        if v is None:
            return "none"
        if v not in REFUND_STATUS:
            raise ValueError("환불 상태는 none · requested · success · rejected 중 하나예요.")
        return v

    @field_validator("cn_last_text", "refund_no")
    @classmethod
    def blank2(cls, v):
        return _blank(v)

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
            return "none"      # 비우면 '모름'
        if v not in CHARGED_STATUS:
            raise ValueError("청구 확인은 none · approved · settled 중 하나예요.")
        return v

    @field_validator("charged_source")
    @classmethod
    def blank_source(cls, v):
        return _blank(v)

    @field_validator("cn_tracking_no")
    @classmethod
    def no_spaces(cls, v):
        v = _blank(v)
        return v.replace(" ", "") if v else v

    @field_validator("shop_name", "cn_courier", "memo")
    @classmethod
    def blank(cls, v):
        return _blank(v)

    @field_validator("item_url")
    @classmethod
    def url(cls, v):
        return _clean_url(v)

    @field_validator("cn_status")
    @classmethod
    def status(cls, v):
        if v not in CN_STATUS:
            raise ValueError("중국 배송 상태가 올바르지 않습니다.")
        return v


class TaobaoPurchaseCreate(_Common):
    order_id: int                                       # 고객 주문 (MarketOrder)
    taobao_order_no: str = Field(max_length=40)

    @field_validator("taobao_order_no")
    @classmethod
    def order_no(cls, v):
        return _order_no(v)


class TaobaoPurchaseUpdate(_Common):
    """PATCH — 보낸 필드만 바꾼다. 붙은 고객 주문은 바꾸지 않는다 (잘못 붙였으면 삭제 후 다시)."""

    taobao_order_no: Optional[str] = Field(default=None, max_length=40)
    cn_status: Optional[str] = None

    @field_validator("taobao_order_no")
    @classmethod
    def order_no(cls, v):
        return _order_no(v)

    @field_validator("cn_status")
    @classmethod
    def status(cls, v):
        if v is None or v not in CN_STATUS:
            raise ValueError("중국 배송 상태가 올바르지 않습니다.")
        return v
