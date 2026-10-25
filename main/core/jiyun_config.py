"""집운 기록 설정. api-contract.md '집운 기록'"""

# 집운 기록 상태 — 배송 요청(결제) → 출고. 통관·국내 배송은 관세청·마켓 쪽 기록으로 따라간다
JIYUN_STATUS = {
    "requested": "배송 요청 (결제)",
    "dispatched": "집운 출고",
    "problem": "문제 (지연·누락·파손)",
    "cancelled": "취소",
}

# 기록(OrderEvent)에 이전값 → 새값으로 남길 칸
JIYUN_TRACKED = (
    "jiyun_no", "status", "packages", "weight_kg", "fee_cny", "transport", "requested_at",
    "pay_method", "pay_currency", "pay_amount", "charged_krw", "charged_status", "charged_at", "charged_source",
    "dispatched_at", "hbl", "kr_courier", "kr_tracking_no", "memo",
)

JIYUN_FIELD_LABEL = {
    "jiyun_no": "집운 번호", "status": "상태", "packages": "묶인 소포", "weight_kg": "무게", "fee_cny": "배송비 위안",
    "transport": "운송", "requested_at": "배송 요청 일시", "pay_method": "결제수단", "pay_currency": "결제 통화",
    "pay_amount": "결제 금액", "charged_krw": "실제 청구 원화", "charged_status": "청구 확인", "charged_at": "결제 일시",
    "charged_source": "확인한 곳", "dispatched_at": "출고 일시", "hbl": "H B/L", "kr_courier": "국내 택배사",
    "kr_tracking_no": "국내 송장", "memo": "메모",
}

PACKAGES_MAX = 20
