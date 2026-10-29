from datetime import date
from ipaddress import ip_address, ip_network
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from schemas.company_account import _clean_url, _required_text

LABEL_MAX = 50
VALUES_MAX = 10


class PublicValueIn(BaseModel):
    label: str = Field(max_length=LABEL_MAX)
    value: str = Field(max_length=500)

    @field_validator("label", "value")
    @classmethod
    def required(cls, v):
        return _required_text(v)


class SecretIn(BaseModel):
    """비밀값 1개. 수정(PATCH)에서 value 를 비우면(null) 같은 label 의 기존 값을 그대로 둔다."""

    label: str = Field(max_length=LABEL_MAX)
    value: Optional[str] = Field(default=None, max_length=2000)

    def __repr__(self) -> str:      # 로그·오류에 비밀값이 찍히지 않게
        return f"SecretIn(label={self.label!r}, value={'***' if self.value else None})"

    __str__ = __repr__

    @field_validator("label")
    @classmethod
    def required(cls, v):
        return _required_text(v)

    @field_validator("value")
    @classmethod
    def strip_empty(cls, v):
        return v if v else None      # 앞뒤 공백도 키의 일부일 수 있어 strip 하지 않는다


def _clean_ips(v: list[str]) -> list[str]:
    out = []
    for raw in v:
        s = raw.strip()
        if not s:
            continue
        try:
            (ip_network if "/" in s else ip_address)(s)
        except ValueError:
            raise ValueError(f"IP 형식이 아닙니다: {s}") from None
        if s not in out:
            out.append(s)
    if len(out) > 20:
        raise ValueError("허용 IP 는 20개까지 넣을 수 있습니다.")
    return out


def _unique_labels(items, what: str):
    labels = [i.label for i in items]
    if len(labels) != len(set(labels)):
        raise ValueError(f"{what} 이름이 겹칩니다.")
    if len(items) > VALUES_MAX:
        raise ValueError(f"{what}은 {VALUES_MAX}개까지 넣을 수 있습니다.")


class _Common(BaseModel):
    url: Optional[str] = Field(default=None, max_length=508)
    public_values: list[PublicValueIn] = Field(default_factory=list)
    issued_on: Optional[date] = None
    expires_on: Optional[date] = None
    reauth_from: Optional[date] = None
    reauth_to: Optional[date] = None
    allowed_ips: list[str] = Field(default_factory=list)
    memo: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        return _clean_url(v)

    @field_validator("allowed_ips")
    @classmethod
    def validate_ips(cls, v):
        return _clean_ips(v or [])

    @field_validator("memo")
    @classmethod
    def blank_memo(cls, v):
        return v.strip() or None if v is not None else None

    @field_validator("public_values")
    @classmethod
    def validate_public(cls, v):
        _unique_labels(v or [], "공개값")
        return v or []

    @model_validator(mode="after")
    def check_dates(self):
        if self.reauth_from and self.reauth_to and self.reauth_from > self.reauth_to:
            raise ValueError("재인증 기간의 시작이 끝보다 늦습니다.")
        if self.issued_on and self.expires_on and self.issued_on > self.expires_on:
            raise ValueError("만료일이 발급일보다 빠릅니다.")
        return self


class ApiCredentialCreate(_Common):
    service: str = Field(max_length=100)
    secrets: list[SecretIn] = Field(min_length=1)

    def __repr__(self) -> str:
        return f"ApiCredentialCreate(service={self.service!r}, secrets={[s.label for s in self.secrets]!r})"

    __str__ = __repr__

    @field_validator("service")
    @classmethod
    def required(cls, v):
        return _required_text(v)

    @field_validator("secrets")
    @classmethod
    def validate_secrets(cls, v):
        _unique_labels(v, "비밀값")
        if any(s.value is None for s in v):
            raise ValueError("비밀값을 모두 입력해주세요.")
        return v


class ApiCredentialUpdate(_Common):
    """PATCH — 보낸 필드만 바꾼다. secrets 를 보내면 그 목록으로 통째로 바꾸되,
    value 가 비어 있는 항목은 같은 label 의 기존 값을 그대로 쓴다 (기존에 없던 label 이면 400)."""

    service: Optional[str] = Field(default=None, max_length=100)
    secrets: Optional[list[SecretIn]] = None

    def __repr__(self) -> str:
        return f"ApiCredentialUpdate(fields={sorted(self.model_fields_set)!r})"

    __str__ = __repr__

    @field_validator("service")
    @classmethod
    def required(cls, v):
        if v is None:
            raise ValueError("서비스 이름을 입력해주세요.")
        return _required_text(v)

    @field_validator("secrets")
    @classmethod
    def validate_secrets(cls, v):
        if v is None:
            raise ValueError("비밀값을 비우려면 항목을 빼지 말고 삭제 후 다시 등록해주세요.")
        if not v:
            raise ValueError("비밀값이 하나 이상 있어야 합니다.")
        _unique_labels(v, "비밀값")
        return v
