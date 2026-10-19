from pydantic import BaseModel, Field, field_validator

from schemas.common import check_url


class PhotoFromUrl(BaseModel):
    url: str = Field(max_length=2000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v):
        v = check_url(v)
        if not v:
            raise ValueError("사진 주소를 입력해주세요.")
        return v
