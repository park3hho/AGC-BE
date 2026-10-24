"""타오바오 구매 · 중국 내 배송 설정. api-contract.md '타오바오 구매'"""

# 중국 내 배송 상태 (판매처 → 집운 창고). 순서대로 진행, problem·cancelled 는 어디서든
CN_STATUS = {
    "ordered": "주문함 (판매처 발송 전)",
    "shipped": "판매처 발송",
    "arrived": "집운 창고 입고",
    "problem": "문제 (지연·누락·파손)",
    "cancelled": "취소·환불",
}

# 기록(OrderEvent)에 이전값 → 새값으로 남길 칸
PURCHASE_TRACKED = (
    "taobao_order_no", "shop_name", "item_url", "items", "paid_cny", "purchased_at", "purchased_by_id",
    "cn_status", "shipped_at", "cn_courier", "cn_tracking_no", "arrived_at", "warehouse_ref",
    "status_source", "memo",
)

PURCHASE_ITEMS_MAX = 30
PURCHASE_LINKS_MAX = 50
