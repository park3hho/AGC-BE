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
                # user — 로그인 계정 · company_account — 회사 외부 서비스 계정 + 비밀번호 열람 기록
                "models.user.user",
                "models.company_account.company_account",
                "aerich.models",
            ],
            "default_connection": "default",
        }
    },
    # 저장은 UTC, 조회도 UTC aware → isoformat() 으로 내려주면 FE 가 KST 로 표시
    "use_tz": True,
    "timezone": "UTC",
}
