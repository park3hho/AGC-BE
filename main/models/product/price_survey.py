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


class PriceSurveyOption(BaseModel):
    """조사한 옵션 1개 조합 + 그 가격. 예) 옵션1=색상 '검정', 옵션2=사이즈 'L', 39.90 위안."""

    survey = fields.ForeignKeyField("models.PriceSurvey", related_name="options", on_delete=fields.CASCADE)
    option1 = fields.CharField(max_length=200)                     # 옵션1
    option2 = fields.CharField(max_length=200, null=True)          # 옵션2 (없는 상품도 있음)
    price_cny = fields.DecimalField(max_digits=12, decimal_places=2)  # 옵션별 가격 (위안)
    photo_url = fields.CharField(max_length=1000, null=True)      # 옵션별 사진 (예: 맛별 사진)
    barcode = fields.CharField(max_length=20, null=True)          # 바코드 (GTIN, 숫자 8~14자리, 중국 상품은 보통 69로 시작) — 쿠팡 공식 브랜드 등록에 필요

    class Meta:
        table = "price_survey_option"
