from tortoise import fields

from models.base import BaseModel


class PriceSurvey(BaseModel):
    """가격 조사 — 제품 1개를 특정 날짜에 조사한 기록. 제품 1 : 조사 N.
    옵션 총 종류는 저장하지 않고 options 개수로 센다 (따로 저장하면 실제 옵션 수와 어긋날 수 있다)."""

    product = fields.ForeignKeyField("models.Product", related_name="price_surveys", on_delete=fields.CASCADE)
    code = fields.CharField(max_length=50, unique=True)            # 조사 코드번호
    survey_date = fields.DateField()                               # 조사일
    photo_url = fields.CharField(max_length=1000, null=True)      # 제품 사진 link (조사 시점)
    taobao_url = fields.CharField(max_length=1000)                # 구매할 타오바오 링크 (공식몰 위주)

    # 국내 판매처 최저가 — 없어도 됨 (원화, 정수)
    coupang_min_price = fields.IntField(null=True)
    coupang_url = fields.CharField(max_length=1000, null=True)
    naver_min_price = fields.IntField(null=True)
    naver_url = fields.CharField(max_length=1000, null=True)
    deleted_at = fields.DatetimeField(null=True)                  # 소프트 삭제 시각 — 값이 있으면 목록·상세에서 숨김

    class Meta:
        table = "price_survey"


class ProductOption(BaseModel):
    """제품 옵션 1개 (맛 × 용량·입수) — 제품 단위로 고정된 판매 옵션의 뿌리 (2026-11-18 옵션 구조 정규화).
    id 는 한 번 정해지면 바뀌지 않는다: 판매가(option_price) · 묶음(product_bundle) · 경쟁가 · 마켓 SKU
    `{제품 코드}-{옵션 id}[x묶음]` · 주문 seller_code 가 이 id 를 쓴다. 예전 price_survey_option 의 id 를 그대로 이어받았다.
    가격 조사를 다시 해도 같은 (옵션1, 옵션2)(공백·대소문자 무시)이면 이 줄을 다시 쓰고, 정말 새 옵션만 새로 만든다.
    지울 때는 deleted_at (소프트 삭제) — id 가 다시 쓰이지 않고 옛 주문 SKU 도 계속 찾아진다."""

    product = fields.ForeignKeyField("models.Product", related_name="options", on_delete=fields.CASCADE)
    option1 = fields.CharField(max_length=200)                     # 옵션1 (맛 등)
    option2 = fields.CharField(max_length=200, null=True)          # 옵션2 (용량·입수, 없는 상품도 있음)
    # 현재 원가 (위안) = 이 옵션을 조사한 살아 있는 조사 중 최근 조사의 값. 조사별 값은 price_survey_price 가 정본이고,
    # 이 칸은 조사 저장 때 services/product/option_service.refresh_current_prices 만 고친다 (직접 쓰지 않는다)
    price_cny = fields.DecimalField(max_digits=12, decimal_places=2)
    photo_url = fields.CharField(max_length=1000, null=True)      # 옵션별 사진 (예: 맛별 사진)
    barcode = fields.CharField(max_length=20, null=True)          # 바코드 (GTIN, 숫자 8~14자리) — 쿠팡 공식 브랜드 등록에 필요
    sort = fields.SmallIntField(default=0)                         # 보이는 순서 (같으면 id 순)
    deleted_at = fields.DatetimeField(null=True)                  # 소프트 삭제 — 값이 있으면 가격 책정·조사 화면에서 숨김
    # 규격 구조 칸 (2026-11-22) — option2 글자를 utils/option_spec.parse_option_spec 로 나눈 값. 마켓 등록·배송비는 이 칸을 먼저 쓰고
    # 비어 있으면 예전 글자 해석으로. option2 를 고치면 자동 다시 해석 (spec_source='manual' 이면 그대로)
    unit_amount = fields.DecimalField(max_digits=10, decimal_places=2, null=True)   # 개당 용량 숫자 (3g×8티백 → 3)
    unit = fields.CharField(max_length=8, null=True)               # g · kg · ml · L
    unit_count = fields.IntField(null=True)                        # 한 묶음 안 개수 (3g×8티백×2박스 → 8)
    count_word = fields.CharField(max_length=8, null=True)         # 티백 · 개입 · 봉 · 병 · 캔 · 포 · 스틱 · 통 …
    pack_count = fields.IntField(null=True, default=1)             # 박스·묶음 수 (괄호 밖 ×2박스 → 2)
    total_count = fields.IntField(null=True)                       # 총 개수 = unit_count × pack_count (섞인 구성은 실제 총 개수)
    spec_note = fields.CharField(max_length=200, null=True)        # 괄호 속 부가 설명 (약 · 상자 크기 · 섞인 구성 등)
    spec_checked = fields.BooleanField(default=False)              # 사람이 확인함
    spec_source = fields.CharField(max_length=8, null=True, default="auto")   # auto (해석기) · manual (사람이 고침)

    class Meta:
        table = "product_option"


class PriceSurveyPrice(BaseModel):
    """가격 조사 1건에서 본 옵션 1개의 가격 (관찰 기록). 조사 1 : N, 제품 옵션 1 : N (조사할 때마다 1줄).
    예) 2026-11-18 조사에서 옵션 66 = 39.90 위안. 조사를 지우면(소프트) 기록은 남고 현재 원가 계산에서만 빠진다."""

    survey = fields.ForeignKeyField("models.PriceSurvey", related_name="observations", on_delete=fields.CASCADE)
    option = fields.ForeignKeyField("models.ProductOption", related_name="observations", on_delete=fields.CASCADE)
    price_cny = fields.DecimalField(max_digits=12, decimal_places=2)  # 그 조사에서 본 가격 (위안)

    class Meta:
        table = "price_survey_price"
        unique_together = (("survey", "option"),)
