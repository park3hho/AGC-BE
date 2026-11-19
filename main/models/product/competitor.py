from tortoise import fields

from models.base import BaseModel


class CompetitorPrice(BaseModel):
    """마켓 최저가 경쟁 확인 1건 = 제품 1개 × 판매처(쿠팡·네이버) × 비교한 옵션 1개 (2026-11-07).
    같은 상품을 그 마켓에서 가장 싸게 파는 판매자(우리 제외)를 적는다. 매일 새벽 점검이 덮어쓴다 —
    최신 값만 두고, 바뀐 기록은 history(최근 30회)에 쌓는다.
    우리 판매가·최소가(마진 바닥)는 저장하지 않고 화면에 낼 때 가격 책정에서 계산한다."""

    product = fields.ForeignKeyField("models.Product", related_name="competitor_prices", on_delete=fields.CASCADE)
    platform = fields.CharField(max_length=10)                       # coupang · naver
    # 비교한 우리 옵션 (가격 조사 옵션). 없으면 대표(가장 싼) 옵션과 비교한 것으로 본다
    option = fields.ForeignKeyField("models.ProductOption", related_name="competitor_prices", null=True,
                                    on_delete=fields.SET_NULL)

    status = fields.CharField(max_length=12, default="found")        # found(경쟁자 있음) · only_us(우리만 팜) · not_found(검색 안 됨)
    vendor_name = fields.CharField(max_length=100, null=True)        # 최저가 판매자 이름 (쿠팡 판매자 · 네이버 스토어)
    vendor_price = fields.IntField(null=True)                        # 그 판매자 가격 (원, 배송비 포함 · 우리 옵션 수량으로 환산)
    vendor_shipping = fields.IntField(null=True)                     # 그중 배송비 (원) — 무료면 0
    vendor_type = fields.CharField(max_length=12, null=True)         # agency(구매대행·해외) · warehouse(국내 재고) · unknown
    vendor_note = fields.CharField(max_length=200, null=True)        # 환산 근거 · 도착 문구 등 (예: "24캔 37,800원 → 15병 환산", "모레 도착")
    vendor_url = fields.CharField(max_length=500, null=True)
    query = fields.CharField(max_length=100, null=True)              # 쓴 검색어
    checked_at = fields.DatetimeField(null=True)
    history = fields.JSONField(default=list)                         # [{at, vendor_name, vendor_price, vendor_type, status}] 최근 30회
    # 확인할 때의 우리 쪽 값 (2026-11-19 확인 대기열) — {our_price, survey_cny, buy_cny, ship_cny, option, title}
    #   지금 값과 다르면 대기열에 '바뀜'으로 다시 올라온다. 다음 저장 때 새 값으로 바뀌어 저절로 풀린다
    basis = fields.JSONField(null=True)
    vendor_ref = fields.JSONField(null=True)                         # 판매자 상품 식별 캐시 (예: 쿠팡 {productId, vendorItemId}, 네이버 {channelProductNo})
    class Meta:
        table = "competitor_price"
        unique_together = (("product", "platform", "option"),)


class CompetitorWatch(BaseModel):
    """최저가 경쟁 점검 설정 1건 = 제품 × 판매처 (× 옵션, 비우면 제품 전체) (2026-11-19).
    점검 루틴이 세션 메모에 들고 다니던 것을 DB 로 — 검색어 지정 · 검색 메모 · 사람 확인 필요 · 재확인 보류 · 확인 필요 표시."""

    product = fields.ForeignKeyField("models.Product", related_name="competitor_watches", on_delete=fields.CASCADE)
    platform = fields.CharField(max_length=10)                       # coupang · naver
    option = fields.ForeignKeyField("models.ProductOption", related_name="competitor_watches", null=True,
                                    on_delete=fields.CASCADE)
    query_override = fields.CharField(max_length=100, null=True)     # 이 검색어로 찾는다 (예: 385 '루이싱 동결건조 커피')
    search_note = fields.CharField(max_length=200, null=True)        # 검색 요령 (예: "원기탄 플랫화이트로는 안 나옴")
    user_note = fields.CharField(max_length=300, null=True)          # 사람이 봐야 할 것 (예: "네이버 444 무가당 여부 확인")
    needs_user_check = fields.BooleanField(default=False)            # true = 같은 제품인지 등 사람 확인 필요 (대기열에 표시만)
    skip_until = fields.DateField(null=True)                         # 이 날(KST)까지 재확인 · 오래된 순 · 검색 안 됨 재시도 건너뜀 (주문 · 바뀜 · 신규는 안 건너뜀)
    flag_reason = fields.CharField(max_length=200, null=True)        # 손으로 '확인 필요' 표시한 사유
    flagged_at = fields.DatetimeField(null=True)                     # 이 뒤에 확인 저장되면 표시가 풀린다

    class Meta:
        table = "competitor_watch"
        unique_together = (("product", "platform", "option"),)