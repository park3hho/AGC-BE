"""상세페이지(디자인) 요청 스키마 — docs/api-contract.md '상세페이지'.

content 는 템플릿 칸 값이다. 모르는 키는 버리고, 빠진 칸은 빈 값으로 채워서 저장한다
(FE 템플릿이 언제나 같은 모양을 받게)."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.detail_page_config import HOW_ICONS

T_SHORT = 100      # 배지 · 칩 · 제목 같은 짧은 칸
T_LINE = 300       # 한 줄 문장
T_TEXT = 1000      # 여러 줄 문장
PHOTO = 1000       # 사진 주소 (product.photo_url 과 같은 길이)

HowIcon = Literal[HOW_ICONS]


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)


class Badge(_In):
    value: str = Field(default="", max_length=T_SHORT)
    label: str = Field(default="", max_length=T_SHORT)


class Hero(_In):
    """S1 대표 사진"""
    eyebrow: str = Field(default="", max_length=T_SHORT)
    headline: str = Field(default="", max_length=T_LINE)        # 줄바꿈 = 줄, *글자* = 파란 강조
    name: str = Field(default="", max_length=T_LINE)
    name_sub: str = Field(default="", max_length=T_LINE)
    badges: list[Badge] = Field(default_factory=list, max_length=4)
    photo_url: Optional[str] = Field(default=None, max_length=PHOTO)   # 원래 비율로, 860 폭 · 최대 1100px 높이 (넘으면 위 기준 자름)


class PointItem(_In):
    title: str = Field(default="", max_length=T_SHORT)
    desc: str = Field(default="", max_length=T_LINE)
    big: str = Field(default="", max_length=20)                 # 오른쪽 큰 숫자
    big_unit: str = Field(default="", max_length=T_SHORT)
    photo_url: Optional[str] = Field(default=None, max_length=PHOTO)   # 있으면 사진 카드 (사진 위 · 글 아래)


class Points(_In):
    """S2 포인트"""
    title: str = Field(default="", max_length=T_SHORT)
    lead: str = Field(default="", max_length=T_LINE)
    items: list[PointItem] = Field(default_factory=list, max_length=4)


class FlavorItem(_In):
    name: str = Field(default="", max_length=T_SHORT)
    name_cn: str = Field(default="", max_length=T_SHORT)
    desc: str = Field(default="", max_length=T_LINE)
    chips: list[str] = Field(default_factory=list, max_length=4)
    photo_url: Optional[str] = Field(default=None, max_length=PHOTO)

    @field_validator("chips")
    @classmethod
    def short_chips(cls, v):
        return [c[:T_SHORT] for c in v if c and c.strip()]


class GalleryItem(_In):
    photo_url: Optional[str] = Field(default=None, max_length=PHOTO)
    caption: str = Field(default="", max_length=T_LINE)


class Gallery(_In):
    """S3 끝 구성 · 포장 사진 (0~4장, 사진 없는 칸은 안 그림)"""
    title: str = Field(default="", max_length=T_SHORT)
    items: list[GalleryItem] = Field(default_factory=list, max_length=4)


class Flavors(_In):
    """S3 맛 선택 — items[].photo_url 은 제품 사진 아무거나"""
    title: str = Field(default="", max_length=T_SHORT)
    lead: str = Field(default="", max_length=T_LINE)
    items: list[FlavorItem] = Field(default_factory=list, max_length=12)
    notes: list[str] = Field(default_factory=list, max_length=4)
    gallery: Gallery = Field(default_factory=Gallery)


class InfoRow(_In):
    label: str = Field(default="", max_length=T_SHORT)
    value: str = Field(default="", max_length=T_TEXT)


class Nutri(_In):
    value: str = Field(default="", max_length=20)
    label: str = Field(default="", max_length=T_SHORT)


class Info(_In):
    """S4 제품 정보"""
    title: str = Field(default="", max_length=T_SHORT)
    rows: list[InfoRow] = Field(default_factory=list, max_length=15)
    nutrition: list[Nutri] = Field(default_factory=list, max_length=6)
    note: str = Field(default="", max_length=T_LINE)
    label_photo_url: Optional[str] = Field(default=None, max_length=PHOTO)   # 현지 라벨 원본 사진 (정보 표 위)
    label_caption: str = Field(default="", max_length=T_LINE)


class HowItem(_In):
    icon: HowIcon = "cup"
    title: str = Field(default="", max_length=T_SHORT)
    desc: str = Field(default="", max_length=T_LINE)


class HowTo(_In):
    """S5 마시는 법 · 보관"""
    title: str = Field(default="", max_length=T_SHORT)
    items: list[HowItem] = Field(default_factory=list, max_length=4)


class DetailContent(_In):
    hero: Hero = Field(default_factory=Hero)
    points: Points = Field(default_factory=Points)
    flavors: Flavors = Field(default_factory=Flavors)
    info: Info = Field(default_factory=Info)
    howto: HowTo = Field(default_factory=HowTo)


class DetailPageSave(BaseModel):
    """PUT /detail-pages/{product_id} — 내용 저장 (없으면 만든다). submit=true 면 검수 요청까지."""
    content: DetailContent
    submit: bool = False


class DetailPageApprove(BaseModel):
    """POST /detail-pages/{product_id}/approve — 휴먼 체크 = 사람이 미리보기를 보고 "확인" 한 번.
    checks 는 예전 FE 호환용으로만 받고 무시한다."""
    checks: Optional[list[str]] = Field(default=None, max_length=20)
    note: Optional[str] = Field(default=None, max_length=T_TEXT)


class DetailPageRequestChanges(BaseModel):
    """POST /detail-pages/{product_id}/request-changes — 무엇을 고칠지 메모 필수."""
    note: str = Field(max_length=T_TEXT)

    @field_validator("note")
    @classmethod
    def need_note(cls, v):
        if not v or not v.strip():
            raise ValueError("무엇을 고쳐야 하는지 적어주세요.")
        return v.strip()


class NoticeItem(_In):
    title: str = Field(default="", max_length=T_SHORT)
    body: str = Field(default="", max_length=T_LINE)


class DetailCommonSave(BaseModel):
    """PUT /detail-pages/common — S6 공통 안내 + 등록번호 (모든 상세페이지에 같이 쓰임)."""
    reg_no: str = Field(default="", max_length=50)
    seller: str = Field(default="", max_length=100)
    notice_title: str = Field(default="", max_length=100)
    notice: list[NoticeItem] = Field(default_factory=list, max_length=10)

    @field_validator("reg_no", "seller", "notice_title")
    @classmethod
    def strip(cls, v):
        return (v or "").strip()
