import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core.permissions import Role

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,50}$")
PASSWORD_MIN_LEN = 8
PASSWORD_MAX_BYTES = 72     # bcrypt 는 72바이트를 넘으면 오류


def check_password(v: str) -> str:
    if len(v) < PASSWORD_MIN_LEN:
        raise ValueError(f"비밀번호는 {PASSWORD_MIN_LEN}자 이상이어야 합니다.")
    if len(v.encode("utf-8")) > PASSWORD_MAX_BYTES:
        raise ValueError("비밀번호가 너무 깁니다. (영문 기준 72자 이하)")
    return v


class UserCreate(BaseModel):
    username: str = Field(max_length=50)
    name: str = Field(max_length=50)
    password: str = Field(max_length=200)
    role: Role

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("아이디는 3~50자 영문·숫자·_ . - 만 쓸 수 있습니다.")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("이름을 입력해주세요.")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return check_password(v)


class UserUpdate(BaseModel):
    active: Optional[bool] = None
    role: Optional[Role] = None
    password: Optional[str] = Field(default=None, max_length=200)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return None if v is None else check_password(v)

    @model_validator(mode="after")
    def at_least_one(self):
        if self.active is None and self.role is None and self.password is None:
            raise ValueError("바꿀 항목이 없습니다.")
        return self
