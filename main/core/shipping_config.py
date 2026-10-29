# core/shipping_config.py
# 배송비 규칙 — 진실의 원천은 여기.
#
# 요금: 타오바오 공식 집운-해운(集运-海运, 경제형) 한국행, "식품·민감 화물(食品敏货)" 0~30kg
#   확인일 2026-10-20 — 타오바오 상품 상세(배송지 한국) › 集运-海运 › 查看计费规则
#   https://world.taobao.com/wow/z/oversea/rule-guide/hFXyydtteWSdFtTPjENn
#   - 첫 1kg 33위안, 넘는 무게는 0.5kg 마다 2위안
#   - 1kg 미만도 1kg, 넘는 무게는 0.5kg 단위로 올림
#   - 실제 무게와 부피 무게 중 큰 값 — 부피 무게는 아직 반영하지 않는다 (음료는 실제 무게가 더 크다)
#   - 소형 한도 30kg (한 변 100cm, 세 변 합 180cm). 넘으면 이 요금표로 보낼 수 없다
#   - 관세·부가세는 포함되지 않음
#   음료가 주력이라 식품 요금으로 고정한다 (2026-10-20 사용자 결정)
#
# 무게: 용량(ml) × 1g + 박스 500g (2026-10-20 사용자 지정). 용량은 옵션 이름에서 읽는다 (utils/volume.py)
# g·kg 로 적힌 옵션은 1g = 1ml 로 본다 (2026-10-24 사용자 결정)

from decimal import Decimal

SHIPPING_SERVICE_LABEL = "타오바오 집운-해운"
SHIPPING_CATEGORY_LABEL = "식품"

SHIPPING_FIRST_KG = Decimal("1")       # 첫 무게 (kg)
SHIPPING_FIRST_CNY = Decimal("33")     # 첫 무게 요금 (위안)
SHIPPING_STEP_KG = Decimal("0.5")      # 추가 무게 단위 (kg)
SHIPPING_STEP_CNY = Decimal("2")       # 추가 단위당 요금 (위안)
SHIPPING_MAX_KG = Decimal("30")        # 소형 한도 (kg)

BOX_WEIGHT_G = 500                     # 박스 무게 (g)
G_PER_ML = 1                           # 음료 1ml = 1g 으로 본다

# ── 부피 무게 (2026-10-29 사용자: 티백은 무게보다 크기가 중요, 모르면 보수적으로) ─────────────
# 계산 무게 = 실제 무게와 부피 무게 중 큰 값. 부피 무게(kg) = 가로×세로×높이(cm) / 6000
#   타오바오 국제물류 안내: 나누는 값은 물류사마다 4500~8000, 집운 안내 예시는 6000
#   https://world.taobao.com/wow/oversea/act/wuliuyunfei
# 차(tea) 제품만 적용 — 음료는 실제 무게가 항상 더 크다.
# 상자 크기는 상세에 없어서 적당한 택배상자 30×20×15cm(세 변 합 65cm, 소형 한도 180cm 안)로 넉넉히 잡는다.
# 묶음 N개는 상자 부피도 N배로 본다 (실제로는 한 상자에 같이 담겨 더 작다 = 보수적).
VOLUMETRIC_DIVISOR = 6000
TEA_BOX_CM = (30, 20, 15)

# ── 타오바오 공식 집운 안내 (화면 표시용, 계산은 위 식품 요율만 쓴다) ───────────────────────────
# 출처: '韩国集运海运-经济型运费报价' 官方物流 · 海运宅配, 확인일 2026-10-29 (Manager 2 조사, 사용자 요청)
SHIPPING_SOURCE_URL = "https://world.taobao.com/wow/z/oversea/rule-guide/hFXyydtteWSdFtTPjENn"
SHIPPING_SOURCE_CHECKED = "2026-10-29"
VOLUMETRIC_SOURCE_URL = "https://world.taobao.com/wow/oversea/act/wuliuyunfei"
SHIPPING_ETA = "합포장 후 6~7일 도착 (결제 화면에는 8~12일로 나오기도 함)"
SHIPPING_RATES = [   # 금액은 위안 문자열
    {"name": "일반 소형", "cn": "普货小件", "range": "0~30kg", "price": "첫 1kg ¥21.5 · 0.5kg마다 ¥2", "applied": False},
    {"name": "식품 소형", "cn": "食品敏货", "range": "0~30kg", "price": "첫 1kg ¥33 · 0.5kg마다 ¥2", "applied": True},
    {"name": "일반 대형", "cn": "普货大件", "range": "30~200kg",
     "price": "30~100kg ¥5.0/kg · 100~150kg ¥19/kg · 150~200kg ¥20/kg (+대형 작업비 별도)", "applied": False},
]
SHIPPING_BILLABLE_RULE = "실제 무게와 부피 무게 중 큰 값"
SHIPPING_ROUNDING = [
    "2.0~30kg: 첫 무게 1kg 미만도 1kg, 추가 무게는 0.5kg 단위 올림",
    "30kg 넘으면 1kg 단위 올림",
]
SHIPPING_SIZE_LIMITS = [
    "소형: 무게 ≤30kg, 가장 긴 변 ≤100cm, 세 변 합 ≤180cm",
    "대형: 실제 무게 30~200kg, 또는 100cm < 가장 긴 변 ≤200cm, 또는 180cm < 세 변 합 ≤300cm",
    "넘으면 집운 창고가 받지 않을 수 있음 — 주문 전에 판매자와 무게·크기 확인",
]
SHIPPING_TAX_NOTE = "운임에 한국 관세·소비세·지방세는 포함되지 않음"
SHIPPING_NOTES = [
    "받는 사람 정보(이름·전화·주소)와 개인통관번호를 정확히 입력",
    "창고 입고 후 직접 합포장하고 운임 결제",
]

# ── 묶음 판매 (2026-10-26 사용자 결정) ─────────────────────────────────────────
# 첫 1kg 요금이 고정이라 한 번에 많이 보낼수록 한 개당 운임이 싸다.
# 제품에서 가장 무거운 옵션도 10kg 미만이면, 그 옵션을 N개 묶어 10kg 이상이 되는 가장 작은 N 을 제안한다.
# 예: 북빙양 330ml×24캔(8.4kg) → ×2 = 48캔(16.3kg). 박스는 묶음 전체에 1개.
# 묶음은 가격 책정의 판매 옵션일 뿐, 가격 조사 옵션(타오바오에서 실제 파는 것)은 그대로 둔다.
BUNDLE_TARGET_KG = Decimal("10")       # 이 무게 이상이 되게 묶는다
BUNDLE_MAX_QTY = 10                     # 묶음 수 상한 (직접 넣을 때도)
# 면세 한도 — 물품가격(타오바오 상품가) 기준 미화 150달러. 위안→달러는 고정 근사값 (환율 API 는 원/위안만 있음)
DUTY_FREE_USD = Decimal("150")
CNY_PER_USD = Decimal("7.1")            # 근사값 — 경고용. 정확한 통관 판단이 아니다


# ── 배송 경로 (출고지 주소의 route) ─────────────────────────────────────────────
# 해외 배대지 → 해운/항공 → 한국 통관 → 국내 택배. 마켓 발송처리(송장 업로드)는 국내 택배사 + 국내 송장번호.
# 택배사 코드 — 쿠팡 Open API '택배사 코드' · 네이버 커머스API '발송 처리' deliveryCompanyCode (확인일 2026-10-24)
#   https://developers-v1.coupangcorp.com/hc/ko/articles/360034156033
#   https://apicenter.commerce.naver.com/docs/commerce-api/2.80.0/seller-dispatch-product-orders-pay-order-seller
# 롯데택배는 두 마켓 모두 옛 이름 코드 HYUNDAI 를 쓴다.
COURIERS = {
    "CJGLS": {"name": "CJ대한통운", "codes": {"쿠팡": "CJGLS", "네이버": "CJGLS"}},
    "HANJIN": {"name": "한진택배", "codes": {"쿠팡": "HANJIN", "네이버": "HANJIN"}},
    "LOTTE": {"name": "롯데택배", "codes": {"쿠팡": "HYUNDAI", "네이버": "HYUNDAI"}},
    "EPOST": {"name": "우체국택배", "codes": {"쿠팡": "EPOST", "네이버": "EPOST"}},
    "KGB": {"name": "로젠택배", "codes": {"쿠팡": "KGB", "네이버": "KGB"}},
}

TRANSPORTS = {"sea": "해운", "air": "항공"}
