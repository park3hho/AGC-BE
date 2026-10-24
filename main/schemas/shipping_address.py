import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core.shipping_config import COURIERS
from schemas.company_account import _required_text

Use = Literal["outbound", "return"]       # 출고지 · 반품(교환)지
CODES_MAX = 20


class MarketCodeIn(BaseModel):
    """마켓 주소록에 등록된 번호 1개 (예: 쿠팡 출고지 코드 25556899)."""

    market: str = Field(max_length=30)               # 자유 입력 — 네이버 · 쿠팡 등
    use: Use
    code: str = Field(max_length=50)
    name: Optional[str] = Field(default=None, max_length=100)   # 마켓에 등록된 이름 (달라도 됨)

    @field_validator("market", "code")
    @classmethod
    def required(cls, v):
        return _required_text(v)

    @field_validator("name")
    @classmethod
    def empty_none(cls, v):
        return (v or "").strip() or None


def _opt(v: Optional[str]) -> Optional[str]:
    return (v or "").strip() or None


class RouteIn(BaseModel):
    """배송 경로 — 해외 배대지 → 해운/항공 → 한국 통관 → 국내 택배. 마켓 발송처리는 courier(국내 택배사) + 국내 송장번호."""

    forwarder: Optional[str] = Field(default=None, max_length=100)      # 국제 물류사 (예: 차이냐오 菜鸟)
    transport: Literal["sea", "air"] = "sea"                           # 해운 · 항공
    port: Optional[str] = Field(default=None, max_length=50)            # 입항 항구 (인천 · 평택)
    courier: Optional[str] = None                                       # 국내 택배사 — core.shipping_config.COURIERS 키
    tracking_when: Optional[str] = Field(default=None, max_length=200)  # 국내 송장번호가 나오는 시점
    customs_ref: Optional[str] = Field(default=None, max_length=200)    # UNI-PASS 통관 조회 번호와 확인 위치
    confirmed: bool = False                                             # 배대지(집운)에 확인했는지
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("forwarder", "port", "tracking_when", "customs_ref", "note")
    @classmethod
    def empty_none(cls, v):
        return _opt(v)

    @field_validator("courier")
    @classmethod
    def known_courier(cls, v):
        v = _opt(v)
        if v is not None and v not in COURIERS:
            raise ValueError("모르는 택배사예요.")
        return v


class _AddressFields(BaseModel):
    @field_validator("country", check_fields=False)
    @classmethod
    def country_code(cls, v):
        if v is None:
            return v
        v = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", v):
            raise ValueError("국가는 2글자 코드로 적어주세요 (예: KR, CN).")
        return v

    @field_validator("name", "address", check_fields=False)
    @classmethod
    def required(cls, v):
        return v if v is None else _required_text(v)

    @field_validator("zip_code", "address_detail", "phone", "memo", check_fields=False)
    @classmethod
    def empty_none(cls, v):
        return _opt(v)

    @field_validator("uses", "defaults", check_fields=False)
    @classmethod
    def unique_uses(cls, v):
        if v is None:
            return v
        return [u for u in ("outbound", "return") if u in v]      # 중복 제거 · 순서 고정

    @model_validator(mode="after")
    def consistent(self):
        uses = getattr(self, "uses", None)
        defaults = getattr(self, "defaults", None)
        codes = getattr(self, "market_codes", None)
        if uses is not None and defaults is not None and not set(defaults) <= set(uses):
            raise ValueError("기본으로 쓰는 용도는 이 주소의 용도 안에서만 고를 수 있어요.")
        if uses is not None and codes is not None:
            if any(c.use not in uses for c in codes):
                raise ValueError("마켓 코드의 용도가 이 주소의 용도에 없어요.")
        if codes is not None:
            keys = [(c.market, c.use) for c in codes]
            if len(keys) != len(set(keys)):
                raise ValueError("같은 마켓·용도의 코드가 두 번 들어갔어요.")
        return self


class ShippingAddressCreate(_AddressFields):
    name: str = Field(max_length=100)
    country: str = "KR"
    zip_code: Optional[str] = Field(default=None, max_length=20)
    address: str = Field(max_length=300)
    address_detail: Optional[str] = Field(default=None, max_length=300)
    phone: Optional[str] = Field(default=None, max_length=40)
    uses: list[Use] = Field(min_length=1)
    defaults: list[Use] = []
    market_codes: list[MarketCodeIn] = Field(default=[], max_length=CODES_MAX)
    route: Optional[RouteIn] = None
    memo: Optional[str] = Field(default=None, max_length=2000)


class ShippingAddressUpdate(_AddressFields):
    """보낸 필드만 바꾼다. uses·defaults·market_codes 는 서로 맞물려서 서비스에서 합친 뒤 다시 검사한다."""

    name: Optional[str] = Field(default=None, max_length=100)
    country: Optional[str] = None
    zip_code: Optional[str] = Field(default=None, max_length=20)
    address: Optional[str] = Field(default=None, max_length=300)
    address_detail: Optional[str] = Field(default=None, max_length=300)
    phone: Optional[str] = Field(default=None, max_length=40)
    uses: Optional[list[Use]] = Field(default=None, min_length=1)
    defaults: Optional[list[Use]] = None
    market_codes: Optional[list[MarketCodeIn]] = Field(default=None, max_length=CODES_MAX)
    route: Optional[RouteIn] = None                                     # null = 지움
    memo: Optional[str] = Field(default=None, max_length=2000)
