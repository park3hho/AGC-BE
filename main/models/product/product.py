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
    # 수입신고용 성분 자료 — 신고 때 상품에 있으면 그대로 쓰고, 없으면 찾아서 여기에 저장한다 (2026-11-14)
    label_images = fields.JSONField(null=True)                    # 성분표·영양성분표 이미지 주소 목록 (최대 10장)
    nutrition = fields.TextField(null=True)                       # 영양성분 글 (예: 100ml당 열량 25kcal, 당류 6g …)
    # 분류 — 값 목록은 utils/category.py (2026-10-29)
    category = fields.CharField(max_length=20, default="beverage")  # 대분류 beverage(음료) · tea(차, 우려 마시는)
    subcategory = fields.CharField(max_length=20, null=True)      # 소분류 — 대분류마다 정해진 값
    tea_form = fields.CharField(max_length=20, null=True)         # 형태 — 차만 (leaf 찻잎 · bag 티백 · coldbrew 냉침 티백 · powder 가루)
    # 배송비 방식 (2026-11-20 사용자) — 쿠팡·네이버는 한 상품에 배송비 방식이 하나라 제품 단위
    #   included 배송비 포함형(무료배송 · 박스/묶음 단위, 운임을 판매가에 포함) · separate 배송비 별도형(마트형 · 낱개, 배송비 9,900원 · 5만 원 이상 무료)
    #   자동 분류: 낱개 계산 무게(실무게·부피무게 중 큰 값) 300g 이상 included, 미만 separate (services/product/shipping_mode.py)
    shipping_mode = fields.CharField(max_length=10, null=True)
    shipping_mode_source = fields.CharField(max_length=6, default="auto")   # auto(자동 분류가 바꿈) · manual(사람이 고름 — 자동이 덮어쓰지 않음)
    unit_weight_g = fields.IntField(null=True)                      # 낱개 계산 무게 (g) — 대표 옵션 (무게 − 상자) ÷ 개수
    unit_count = fields.IntField(null=True)                         # 대표 옵션의 개수 (×15병 → 15)
    shipping_mode_note = fields.CharField(max_length=200, null=True)  # 계산 근거 (예: "망고맛 500ml×15병 · 7,500g÷15 = 500g")
    deleted_at = fields.DatetimeField(null=True)                  # 소프트 삭제 시각 — 값이 있으면 목록·상세에서 숨김

    class Meta:
        table = "product"
