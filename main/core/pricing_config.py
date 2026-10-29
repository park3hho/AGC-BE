# core/pricing_config.py
# 가격 책정 상수 — 판매처 목록 · 기본값. 진실의 원천은 여기.

from enum import Enum


class Platform(str, Enum):
    COUPANG = "coupang"
    NAVER = "naver"
    SHOP = "shop"          # 자사몰 eidofood.com (2026-10-29) — 마켓이 아니라 가격만 정한다. SHOP-BE 가 읽는다


# 마켓 = 상품 등록 · 주문 수집 · "가격 책정 완료" 기준이 되는 판매처 (자사몰 제외)
MARKET_PLATFORMS = (Platform.COUPANG, Platform.NAVER)


# 배송비 기본값 (원/개) — 더 이상 계산에 쓰지 않는다 (2026-10-20).
#   배송비는 옵션 용량으로 무게를 잡아 집운 요금표로 계산한다 (core/shipping_config.py).
#   product_pricing.shipping_fee 컬럼을 채우는 기본값으로만 남아 있다.
DEFAULT_SHIPPING_FEE = 10000

# 환율 기본값 (원/위안) — exchange_rate 에 한 건도 없을 때 쓴다 (2026-10-19 사용자 지정)
DEFAULT_FX_RATE = 200


class FxSource(str, Enum):
    """exchange_rate.source — 환율을 어디서 받았는지. FE pricingConst.FX_SOURCE_LABEL 과 같아야 한다."""
    MANUAL = "manual"      # 환율 설정 화면에서 사람이 넣음 — 그날은 자동으로 덮어쓰지 않는다
    HANA = "hana"          # 하나은행 고시 매매기준율 (자동)
    OPEN_ER = "open_er_api"  # open.er-api (자동, 하나은행을 못 받을 때 예비)
    DEFAULT = "default"    # 저장된 환율이 없어 DEFAULT_FX_RATE 를 씀 (DB 에는 저장하지 않는 값)


# 환율 자동 받기 (2026-10-21) — services/pricing/fx_fetch.py
#   1순위 하나은행 고시 매매기준율: 네이버 금융 데이터 (키 불필요, 비공식 경로라 바뀔 수 있음)
#   2순위 open.er-api (키 불필요, 하루 1번 갱신)
#   한국수출입은행 공식 API 는 인증키가 필요해서 쓰지 않음
FX_HANA_URL = "https://m.stock.naver.com/front-api/marketIndex/productDetail?category=exchange&reutersCode=FX_CNYKRW"
FX_OPEN_ER_URL = "https://open.er-api.com/v6/latest/CNY"
# 추이 그래프 — GET /exchange-rate?days= 최대 (서버가 저장한 기록 exchange_rate_log)
FX_TREND_MAX_DAYS = 400
FX_TREND_DAILY_AFTER_DAYS = 31  # 이보다 긴 기간은 하루 마지막 값 하나씩 (매시간 기록이라 1년이면 8천 줄)
FX_FETCH_TIMEOUT_SEC = 10
# 매일 이 시각(KST)에 오늘 환율을 한 번 받는다 — 하나은행 1회차 고시가 8시 25분쯤 나온다 (2026-10-21 확인)
FX_DAILY_HOUR = 9
FX_DAILY_MINUTE = 0
FX_RETRY_SEC = 600               # 못 받으면 10분 뒤 다시
FX_RETRY_MAX = 6                 # 최대 6번 (1시간) — 그래도 안 되면 다음 날, 그동안은 마지막 저장값
FX_SANE_MIN = 100               # 이 범위를 벗어난 값은 잘못 받은 것으로 보고 버린다 (원/위안)
FX_SANE_MAX = 400


# 환율 설정 화면에 보여줄 최근 기록 수
FX_HISTORY_SIZE = 30

# 실결제 환율 가산율 (%) — 고시 환율 대비 카드·알리페이 수수료. 실제 결제 내역으로 확정 전까지 0
DEFAULT_FX_MARKUP_PCT = 0

# 판매처별 수수료 기본값 (%, VAT 포함) — 아직 저장 안 된 판매처 설정에 자동으로 넣는다 (2026-10-19 사용자 지정)
#   쿠팡: 플랫폼 = 식품 카테고리 판매수수료 10.6% + VAT → 11.66. 결제 = 0 (공식 안내상 판매수수료에 포함, 별도 결제수수료 없음)
#   네이버: 플랫폼 = 스마트스토어 판매수수료 3% (일반 유입, VAT 포함). 결제 = Npay 주문관리 수수료 일반 등급 3.63% (VAT 포함)
DEFAULT_FEE_RATES = {
    Platform.COUPANG: {"platform_fee_rate": "11.66", "payment_fee_rate": "0"},
    Platform.NAVER: {"platform_fee_rate": "3", "payment_fee_rate": "3.63"},
    # 자사몰: 판매수수료 없음. 결제 = 네이버페이 결제형 · 카카오페이 온라인 영세 등급 약 0.9~0.96% → 1%로 어림 (2026-10-26 조회)
    Platform.SHOP: {"platform_fee_rate": "0", "payment_fee_rate": "1"},
}
