from pydantic import BaseModel, Field, field_validator

USAGE_MAX_LEN = 30
USAGES_MAX = 10


class CompanyAccountCreate(BaseModel):
    platform: str = Field(max_length=100)
    login_id: str = Field(max_length=200)
    password: str = Field(min_length=1, max_length=500)    # 앞뒤 공백도 비밀번호일 수 있으니 그대로 저장
    usages: list[str] = Field(default_factory=list)

    def __repr__(self) -> str:      # 로그·오류 메시지에 비밀번호가 찍히지 않게
        return f"CompanyAccountCreate(platform={self.platform!r}, login_id={self.login_id!r}, usages={self.usages!r})"

    __str__ = __repr__

    @field_validator("platform", "login_id")
    @classmethod
    def required_text(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("값을 입력해주세요.")
        return v

    @field_validator("usages")
    @classmethod
    def validate_usages(cls, v):
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
