"""30분 점검 규칙화 (2026-11-19) — 할 일 종류 · 알림 종류. 루틴 메모 대신 서버가 계산·기록한다."""

# AI·서버 알림 종류 (agent_alert.kind)
ALERT_KIND = {
    "order_new": "새 주문", "purchase_blocked": "구매 막힘", "alipay_low": "알리페이 잔액",
    "login_needed": "로그인 필요", "jiyun_pay_needed": "집운 결제 필요", "bundle_partial": "묶음 일부 입고",
    "package_partial": "소포 일부 입고", "jiyun_paid": "집운 결제 기록", "dispatched": "집운 출고",
    "invoice_sent": "송장 등록", "import_sent": "수입신고 전송", "import_error": "수입신고 오류",
    "claim": "취소·반품", "refund": "환불", "deadline_d3": "발송기한 D-3", "deadline_d1": "발송기한 D-1",
    "deadline_over": "출고지연", "stock_aging": "재고 오래됨", "card_confirmed": "카드값 확정", "other": "기타",
}
ALERT_LEVEL = {"info": "알림", "action": "할 일", "blocked": "막힘"}

# 할 일 종류 — (라벨, group, priority). group: action 지금 할 일 · wait 기다림(확인만)
TASK_TYPE = {
    "claim": ("클레임 확인", "action", 10),
    "confirm": ("발주확인", "action", 20),
    "naver_delay": ("네이버 발송지연", "action", 25),
    "import_decl": ("수입신고 내기", "action", 30),
    "import_status": ("수입신고 처리 확인", "action", 35),
    "cancel_followup": ("취소 뒤 환불·재고", "action", 40),
    "purchase": ("타오바오 구매", "action", 50),
    "jiyun_pay_notice": ("집운 결제 안내", "action", 60),
    "invoice": ("송장 → 마켓 발송처리", "action", 70),
    "deadline": ("발송기한", "action", 75),
    "dispatch_check": ("집운 출고 확인", "wait", 80),
    "stock_aging": ("재고 14일 넘음", "action", 85),
    "jiyun_pay_wait": ("집운 결제 대기 (사용자)", "wait", 88),
    "refund_wait": ("환불 결과 대기", "wait", 90),
    "cn_track": ("중국 물류 확인", "wait", 95),
}
STOCK_AGING_DAYS = 14
CANCEL_LOOKBACK_DAYS = 7
