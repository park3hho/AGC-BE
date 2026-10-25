from tortoise import fields

from models.base import BaseModel


class Product(BaseModel):
    """제품 — 판매할 상품 1건. 제품 코드 추가일 = created_at."""

    code = fields.CharField(max_length=50, unique=True)            # 제품 코드
    photo_url = fields.CharField(max_length=1000, null=True)      # 제품 사진 (이미지 주소)
    photos = fields.JSONField(null=True)                          # 추가 사진 갤러리 — 주소 목록, 순서대로, 최대 10장 (대표 사진 제외)
    title_cn = fields.CharField(max_length=300)                   # 중국어 제목 (타오바오 원제)
    title_ko = fields.CharField(max_length=300, null=True)        # 한국어 제목 (판매용)
    deleted_at = fields.DatetimeField(null=True)                  # 소프트 삭제 시각 — 값이 있으면 목록·상세에서 숨김

    class Meta:
        table = "product"
