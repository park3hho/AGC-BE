from tortoise import fields

from models.base import BaseModel


class Product(BaseModel):
    """제품 — 판매할 상품 1건. 제품 코드 추가일 = created_at."""

    code = fields.CharField(max_length=50, unique=True)            # 제품 코드
    photo_url = fields.CharField(max_length=1000, null=True)      # 제품 사진 (이미지 주소)
    title_cn = fields.CharField(max_length=300)                   # 중국어 제목 (타오바오 원제)
    title_ko = fields.CharField(max_length=300, null=True)        # 한국어 제목 (판매용)

    class Meta:
        table = "product"
