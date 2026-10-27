from tortoise import fields

from models.base import BaseModel


class Product(BaseModel):
    """제품 — 판매할 상품 1건. 제품 코드 추가일 = created_at."""

    code = fields.CharField(max_length=50, unique=True)            # 제품 코드
    photo_url = fields.CharField(max_length=1000, null=True)      # 제품 사진 (이미지 주소)
    photo_hover_url = fields.CharField(max_length=1000, null=True)  # 대표이미지(전환용) — 자사몰 카드에 마우스를 올리면 바뀌는 두 번째 연출컷 (2026-10-27)
    photos = fields.JSONField(null=True)                          # 추가 사진 갤러리 — 주소 목록, 순서대로, 최대 10장 (대표 사진 제외)
    title_cn = fields.CharField(max_length=300)                   # 중국어 제목 (타오바오 원제)
    title_ko = fields.CharField(max_length=300, null=True)        # 한국어 제목 (판매용)
    # 제품 정보 — 리서치 때 함께 찾아 저장하고, 상세페이지 '제품 정보' 표가 이 값을 쓴다 (2026-10-27)
    manufacturer = fields.CharField(max_length=300, null=True)    # 제조사 (공장 법인명, 예: 广东健力宝股份有限公司)
    ingredients = fields.TextField(null=True)                     # 원재료 — 맛마다 다르면 줄마다 "맛: 원재료"
    allergens = fields.CharField(max_length=300, null=True)       # 알레르기 유발 성분 (예: 우유, 대두)
    shelf_life = fields.CharField(max_length=100, null=True)      # 소비기한 (예: 12개월)
    storage = fields.CharField(max_length=300, null=True)         # 보관 방법
    deleted_at = fields.DatetimeField(null=True)                  # 소프트 삭제 시각 — 값이 있으면 목록·상세에서 숨김

    class Meta:
        table = "product"
