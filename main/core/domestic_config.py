"""국내 배송 기록 설정. api-contract.md '국내 배송 기록' (2026-11-03)

국내 배송 기록 1건 = 국내 택배 송장 1개. 타오바오 구매기록 → 집운 기록 → 국내 배송 기록 순서의 마지막 칸.
- 집운 기록에 국내 송장이 들어가면, 또는 마켓(네이버·쿠팡) 원본에 송장이 보이면 자동으로 만든다
- 자동 수집(5분) 때 마켓 발송처리 정보와 배송 조회(tracker.delivery)를 갱신한다 — 같은 송장은 30분에 한 번
"""

from datetime import timedelta

# 상태 — 자동 갱신이 정한다. problem · cancelled 는 사람이 정하고 자동 갱신이 덮지 않는다
DOMESTIC_STATUS = {
    "ready": "송장 나옴 (발송처리 전)",
    "dispatched": "마켓 발송처리",
    "delivering": "배송 중",
    "delivered": "배송 완료",
    "problem": "문제 (오배송·분실·반송)",
    "cancelled": "취소",
}
MANUAL_STATUS = ("problem", "cancelled")

# 어디서 생겼나
DOMESTIC_SOURCE = {"jiyun": "집운 기록", "market": "마켓 주문", "manual": "직접 입력"}

# 기록(OrderEvent)에 이전값 → 새값으로 남길 칸 — 배송 조회 단계(track_*)는 많아서 남기지 않는다
DOMESTIC_TRACKED = (
    "courier", "tracking_no", "status", "market_courier", "market_tracking_no", "market_sent_at", "delivered_at", "memo",
)

DOMESTIC_FIELD_LABEL = {
    "courier": "택배사", "tracking_no": "송장", "status": "상태", "market_courier": "마켓 택배사",
    "market_tracking_no": "마켓 송장", "market_sent_at": "마켓 발송처리 일시", "delivered_at": "배송 완료 일시", "memo": "메모",
}

# 배송 조회 — tracker.delivery (택배사 id 는 core/shipping_config.COURIERS[*].tracker)
TRACKER_URL = "https://apis.tracker.delivery/carriers/{carrier}/tracks/{no}"
TRACK_RECHECK = timedelta(minutes=30)
TRACK_GIVE_UP = timedelta(days=30)     # 만든 뒤 30일이 지나도 배송 완료가 안 보이면 더 묻지 않는다
TRACK_EVENTS_MAX = 40

# 마켓 상태가 이것이면 배송 완료로 본다
MARKET_DELIVERED = {"DELIVERED", "PURCHASE_DECIDED", "FINAL_DELIVERY"}
