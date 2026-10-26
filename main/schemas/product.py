from typing import Optional

PHOTOS_MAX = 10  # 제품 추가 사진(갤러리) 최대 장수

from pydantic import BaseModel, Field, field_validator

from schemas.common import check_photo_url, clean_str


class ProductCreate(BaseModel):
    # code 는 BE 가 발급한다 (PR-YYMMDD-XXXX, utils/code_gen.py)
    photo_url: Optional[str] = Field(default=None, max_length=1000)
    title_cn: str = Field(max_length=300)
    title_ko: Optional[str] = Field(default=None, max_length=300)
    photos: Optional[list[str]] = None  # 추가 사진 (대표 사진 제외), 최대 PHOTOS_MAX
    # 제품 정보 (리서치 때 함께 찾는다) — 비워도 된다
    manufacturer: Optional[str] = Field(default=None, max_length=300)
    ingredients: Optional[str] = Field(default=None, max_length=5000)
    allergens: Optional[str] = Field(default=None, max_length=300)
    shelf_life: Optional[str] = Field(default=None, max_length=100)
    storage: Optional[str] = Field(default=None, max_length=300)

    @field_validator("manufacturer", "ingredients", "allergens", "shelf_life", "storage")
    @classmethod
    def validate_info(cls, v):
        return clean_str(v)

    @field_validator("title_cn")
    @classmethod
    def validate_title_cn(cls, v):
        v = clean_str(v)
        if not v:
            raise ValueError("중국어 제목을 입력해주세요.")
        return v

    @field_validator("title_ko")
    @classmethod
    def validate_title_ko(cls, v):
        return clean_str(v)

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v):
        return check_photo_url(v)


    @field_validator("photos")
    @classmethod
    def validate_photos(cls, v):
        return check_photos(v)


class ProductUpdate(BaseModel):
    """보낸 필드만 바꾼다 (model_dump(exclude_unset=True)). 코드·추가일은 바꿀 수 없다."""

    photo_url: Optional[str] = Field(default=None, max_length=1000)
    title_cn: Optional[str] = Field(default=None, max_length=300)
    title_ko: Optional[str] = Field(default=None, max_length=300)
    photos: Optional[list[str]] = None  # 보내면 목록 전체 교체 · [] 이면 비움
    # 제품 정보 — 보낸 것만 바꾼다, "" 나 null 이면 비움
    manufacturer: Optional[str] = Field(default=None, max_length=300)
    ingredients: Optional[str] = Field(default=None, max_length=5000)
    allergens: Optional[str] = Field(default=None, max_length=300)
    shelf_life: Optional[str] = Field(default=None, max_length=100)
    storage: Optional[str] = Field(default=None, max_length=300)

    @field_validator("manufacturer", "ingredients", "allergens", "shelf_life", "storage")
    @classmethod
    def validate_info(cls, v):
        return clean_str(v)

    @field_validator("title_cn")
    @classmethod
    def validate_title_cn(cls, v):
        v = clean_str(v)
        if not v:
            raise ValueError("중국어 제목은 비울 수 없습니다.")
        return v

    @field_validator("title_ko")
    @classmethod
    def validate_title_ko(cls, v):
        return clean_str(v)

    @field_validator("photo_url")
    @classmethod
    def validate_photo_url(cls, v):
        return check_photo_url(v)

    @field_validator("photos")
    @classmethod
    def validate_photos(cls, v):
        return check_photos(v)


def check_photos(v):
    """추가 사진 목록 — 각 주소는 photo_url 과 같은 규칙, 같은 주소는 한 번, 최대 PHOTOS_MAX 장."""
    if v is None:
        return None
    out = []
    for url in v:
        url = check_photo_url(url)
        if url and url not in out:
            out.append(url)
    if len(out) > PHOTOS_MAX:
        raise ValueError(f"추가 사진은 최대 {PHOTOS_MAX}장입니다.")
    return out