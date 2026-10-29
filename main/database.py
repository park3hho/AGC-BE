import os

TORTOISE_ORM = {
    "connections": {
        "default": os.getenv("DATABASE_URL"),
    },
    "apps": {
        "models": {
            "models": [
                # 새 모델 모듈은 여기에 추가해야 인식된다
                # product — 제품 + 가격 조사
                "models.product.product",
                "models.product.price_survey",
                "models.product.pricing",       # 판매처별 가격 설정 · 옵션 판매가 · 환율 캐시
                "models.product.detail_page",   # 상세페이지(디자인) · 검수 기록 · S6 공통 안내
                "models.product.listing",       # 마켓 등록 기록 (쿠팡·네이버에 올린 상품)
                # user — 로그인 계정 · company_account — 회사 외부 서비스 계정 + 비밀번호 열람 기록
                "models.user.user",
                "models.company_account.company_account",
                "models.company_account.api_credential",   # API 키 묶음 · 비밀값 · 열람 기록
                "models.company_account.company_info",     # 회사 정보 › 기본 정보 (번호·계좌·서류) + 서류 파일
                "models.shipping.address",   # 출고지·반품지 주소록 (마켓 주소 코드)
                "models.order.order",   # 마켓 주문 · 추적 기록(OrderEvent) · 수집 기록(OrderSyncRun)
                "models.order.purchase",   # 타오바오 구매 · 중국 내 배송 (마켓 주문과 다대다)
                "models.order.jiyun",   # 집운 기록 — 배송 요청 · 배송비 결제 · 출고 · 국제 운송장 · 국내 송장
                "models.order.document",   # 주문 증빙 파일 — 타오바오 영수증 · 집운 결제 내역 · 마켓 정산 내역
                "aerich.models",
            ],
            "default_connection": "default",
        }
    },
    # 저장은 UTC, 조회도 UTC aware → isoformat() 으로 내려주면 FE 가 KST 로 표시
    "use_tz": True,
    "timezone": "UTC",
}
