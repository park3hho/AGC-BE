from typing import Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

USAGE_MAX_LEN = 30
USAGES_MAX = 10
URL_MAX_LEN = 500
MEMO_MAX_LEN = 1000


def _clean_memo(v: Optional[str]) -> Optional[str]:
    return (v or "").strip() or None


def _required_text(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("값을 입력해주세요.")
    return v


def _clean_url(v: Optional[str]) -> Optional[str]:
    """빈 값 → None. 'www.foodsafetykorea.go.kr' 처럼 주소만 쓰면 https:// 를 붙인다. http/https 만 허용."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if "://" not in v:
        v = "https://" + v
    parts = urlsplit(v)
    if parts.scheme not in ("http", "https") or not parts.netloc or " " in v:
        raise ValueError("홈페이지 주소를 확인해주세요 (예: https://www.foodsafetykorea.go.kr).")
    if len(v) > URL_MAX_LEN:
        raise ValueError(f"홈페이지 주소는 {URL_MAX_LEN}자 이하로 입력해주세요.")
    return v


def _clean_usages(v: list[str]) -> list[str]:
    out: list[str] = []
    for u in v:
        u = u.strip()
        if not u:
            continue
        if len(u) > USAGE_MAX_LEN:
            raise ValueError(f"용도는 {USAGE_MAX_LEN}자 이하로 입력해주세요.")
        if u not in out:
            out.append(u)
    if len(out) > USAGES_MAX:
        raise ValueError(f"용도는 {USAGES_MAX}개까지 넣을 수 있습니다.")
    return out


class CompanyAccountCreate(BaseModel):
    platform: str = Field(max_length=100)                   # 자유 입력 (정해진 목록 없음)
    login_id: str = Field(max_length=200)
    password: str = Field(min_length=1, max_length=500)    # 앞뒤 공백도 비밀번호일 수 있으니 그대로 저장
    usages: list[str] = Field(default_factory=list)
    url: Optional[str] = Field(default=None, max_length=URL_MAX_LEN + 8)   # 홈페이지 — 없어도 됨
    memo: Optional[str] = Field(default=None, max_length=MEMO_MAX_LEN)     # 비고 — 없어도 됨

    def __repr__(self) -> str:      # 로그·오류 메시지에 비밀번호가 찍히지 않게
        return f"CompanyAccountCreate(platform={self.platform!r}, login_id={self.login_id!r}, usages={self.usages!r})"

    __str__ = __repr__

    @field_validator("platform", "login_id")
    @classmethod
    def required_text(cls, v):
        return _required_text(v)

    @field_validator("usages")
    @classmethod
    def validate_usages(cls, v):
        return _clean_usages(v)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        return _clean_url(v)

    @field_validator("memo")
    @classmethod
    def validate_memo(cls, v):
        return _clean_memo(v)


class CompanyAccountUpdate(BaseModel):
    """PATCH — 보낸 필드만 바꾼다. password 는 보냈을 때만 새로 암호화해 바꾼다. url 에 null/"" 을 보내면 지운다."""

    platform: Optional[str] = Field(default=None, max_length=100)
    login_id: Optional[str] = Field(default=None, max_length=200)
    password: Optional[str] = Field(default=None, min_length=1, max_length=500)
    usages: Optional[list[str]] = None
    url: Optional[str] = Field(default=None, max_length=URL_MAX_LEN + 8)
    memo: Optional[str] = Field(default=None, max_length=MEMO_MAX_LEN)     # null/"" = 지움

    def __repr__(self) -> str:
        return f"CompanyAccountUpdate(fields={sorted(self.model_fields_set)!r})"

    __str__ = __repr__

    @field_validator("platform", "login_id")
    @classmethod
    def required_text(cls, v):
        if v is None:
            raise ValueError("값을 입력해주세요.")
        return _required_text(v)

    @field_validator("password")
    @classmethod
    def password_not_null(cls, v):
        if v is None:
            raise ValueError("비밀번호를 바꾸지 않으려면 password 를 빼고 보내주세요.")
        return v

    @field_validator("usages")
    @classmethod
    def validate_usages(cls, v):
        if v is None:
            raise ValueError("용도를 비우려면 빈 배열을 보내주세요.")
        return _clean_usages(v)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        return _clean_url(v)

    @field_validator("memo")
    @classmethod
    def validate_memo(cls, v):
        return _clean_memo(v)
