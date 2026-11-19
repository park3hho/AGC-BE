"""최저가 경쟁 확인 대기열 가중치 — 점수 = 사유 + 경과 + 매출 + 경쟁 (2026-11-19, 사용자 승인).
가중치를 바꿀 때는 여기만 고친다. 설명: AGC docs/api-contract.md '최저가 경쟁 확인 대기열'."""

# 1) 사유 점수 — 마지막 확인 뒤에 생긴 사유만 (저장하면 0). 여러 개면 가장 큰 값 + 나머지 각각의 절반
REASON_POINTS = {
    "order": 40,      # 주문 들어옴 (확인이 24시간보다 오래됐고 그 뒤 주문)
    "price": 35,      # 판매가 수정
    "flag": 35,       # 손으로 단 '확인 필요' 표시 (PUT /watch flag_reason)
    "new": 30,        # 신규 등록 — 확인 전 · 새 옵션 · 새 마켓 등록
    "cost": 30,       # 원가 수정 (조사가 · 실구매가 · 운임)
    "option": 20,     # 옵션명 · 상품명 수정
    "retry": 10,      # 지난번 not_found — 다시 찾기
}
REASON_CATEGORY = {"order": "order", "price": "price", "flag": "flag", "new": "new", "new_option": "new", "listing": "new",
                   "cost": "cost", "option": "option", "title": "option", "retry": "retry"}
REASON_EXTRA_RATIO = 0.5

# 2) 경과 점수 = 마지막 확인 뒤 경과일 × 하루당 점수 (상한 없음, 확인 전 신규는 0)
AGING_PER_DAY = {"match": 3, "lose": 3, "cheapest_close": 3, "cheapest": 2, "only_us": 1, "unchecked": 1}
CLOSE_GAP_PCT = 3          # cheapest 인데 경쟁가가 우리보다 이 % 안쪽으로 비쌈 → '차이 작음'

# 3) 매출 점수 = 그 판매처 최근 SALES_DAYS 일 주문 1건당 SALES_PER_ORDER, 최대 SALES_MAX (시험 주문 제외)
SALES_DAYS = 30
SALES_PER_ORDER = 5
SALES_MAX = 20

# 4) 경쟁 점수 (지난 확인 결과)
COMPETITION_POINTS = {"match": 20, "lose": 15, "cheapest_close": 10}
COMP_PRICE_MOVED = 10       # 최근 history 에서 경쟁자 가격이 바뀐 적 있음
COMP_HISTORY_WINDOW = 5     # 최근 몇 번의 확인을 볼지
COMP_AGENCY = 5             # 경쟁자가 구매대행(agency)

# 제외 — 보류(skip_until) 기간 · 사람 확인 필요(needs_user_check) · 이 시간 안에 확인했고 그 뒤 새 사유 없음
FRESH_HOURS = 24