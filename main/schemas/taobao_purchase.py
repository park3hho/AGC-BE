from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from core.purchase_config import CN_STATUS, PURCHASE_ITEMS_MAX, PURCHASE_LINKS_MAX
from schemas.company_account import _clean_url


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


class OrderLinkIn(BaseModel):
    order_id: int
    quantity: Optional[int] = Field(default=None, ge=1, le=9999)


def _blank(v):
    if v is None:
        return None
    v = v.strip()
    return v or None


def _clean_links(v: list[OrderLinkIn]) -> list[OrderLinkIn]:
    ids = [l.order_id for l in v]
    if len(ids) != len(set(ids)):
        raise ValueError("같은 마켓 주문이 두 번 연결됐습니다.")
    if not v:
        raise ValueError("마켓 주문을 하나 이상 연결해주세요.")
    if len(v) > PURCHASE_LINKS_MAX:
        raise ValueError(f"마켓 주문은 {PURCHASE_LINKS_MAX}개까지 연결할 수 있습니다.")
    return v


class _Common(BaseModel):
    taobao_order_no: Optional[str] = Field(default=None, max_length=40)
    shop_name: Optional[str] = Field(default=None, max_length=200)
    item_url: Optional[str] = Field(default=None, max_length=508)
    items: list[PurchaseItemIn] = Field(default_factory=list, max_length=PURCHASE_ITEMS_MAX)
    paid_cny: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("9999999"), decimal_places=2)
    purchased_at: Optional[datetime] = None
    cn_status: str = "ordered"
    shipped_at: Optional[datetime] = None
    cn_courier: Optional[str] = Field(default=None, max_length=50)
    cn_tracking_no: Optional[str] = Field(default=None, max_length=60)
    arrived_at: Optional[datetime] = None
    warehouse_ref: Optional[str] = Field(default=None, max_length=60)
    memo: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("taobao_order_no", "cn_tracking_no", "warehouse_ref")
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
    orders: list[OrderLinkIn]

    @field_validator("orders")
    @classmethod
    def links(cls, v):
        return _clean_links(v)


class TaobaoPurchaseUpdate(_Common):
    """PATCH — 보낸 필드만 바꾼다. orders 를 보내면 연결을 그 목록으로 통째로 바꾼다."""

    cn_status: Optional[str] = None
    orders: Optional[list[OrderLinkIn]] = None

    @field_validator("cn_status")
    @classmethod
    def status(cls, v):
        if v is None or v not in CN_STATUS:
            raise ValueError("중국 배송 상태가 올바르지 않습니다.")
        return v

    @field_validator("orders")
    @classmethod
    def links(cls, v):
        if v is None:
            raise ValueError("마켓 주문을 하나 이상 연결해주세요.")
        return _clean_links(v)
