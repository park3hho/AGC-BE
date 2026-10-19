# core/pricing_config.py
# 가격 책정 상수 — 판매처 목록 · 기본값. 진실의 원천은 여기.

from enum import Enum


class Platform(str, Enum):
    COUPANG = "coupang"
    NAVER = "naver"


# 배송비 기본값 (원/개) — 더 이상 계산에 쓰지 않는다 (2026-10-20).
#   배송비는 옵션 용량으로 무게를 잡아 집운 요금표로 계산한다 (core/shipping_config.py).
#   product_pricing.shipping_fee 컬럼을 채우는 기본값으로만 남아 있다.
DEFAULT_SHIPPING_FEE = 10000

# 환율 기본값 (원/위안) — exchange_rate 에 한 건도 없을 때 쓴다 (2026-10-19 사용자 지정)
DEFAULT_FX_RATE = 200


class FxSource(str, Enum):
    """exchange_rate.source — 환율을 어디서 받았는지. 환율 API 를 붙이면 API 이름을 추가한다."""
    MANUAL = "manual"      # 환율 설정 화면에서 사람이 넣음
    DEFAULT = "default"    # 저장된 환율이 없어 DEFAULT_FX_RATE 를 씀 (DB 에는 저장하지 않는 값)


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
}
