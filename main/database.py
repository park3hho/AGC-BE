import os

TORTOISE_ORM = {
    "connections": {
        "default": os.getenv("DATABASE_URL"),
    },
    "apps": {
        "models": {
            "models": [
                # 새 모델 모듈은 여기에 추가해야 인식된다 (예: "models.user.user")
                "aerich.models",
            ],
            "default_connection": "default",
        }
    },
    # 저장은 UTC, 조회도 UTC aware → isoformat() 으로 내려주면 FE 가 KST 로 표시
    "use_tz": True,
    "timezone": "UTC",
}
