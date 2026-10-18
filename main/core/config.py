# core/config.py
# FastAPI 미들웨어 설정 (CORS, Session) + 프로젝트 경로 상수

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

logger = logging.getLogger(__name__)


def setup_middlewares(app: FastAPI):
    is_production = os.getenv("ENV", "dev") != "dev"

    # CORS — production 에서는 http:// · localhost · 127.0.0.1 origin 자동 제거
    raw_origins = os.getenv("ALLOWED_ORIGINS", "")
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
    if is_production:
        unsafe = [
            o for o in allowed_origins
            if o.lower().startswith("http://") or any(h in o.lower() for h in ("localhost", "127.0.0.1", "0.0.0.0"))
        ]
        if unsafe:
            logger.warning(f"CORS: production 환경에서 위험 origin 무시됨: {unsafe}")
        allowed_origins = [o for o in allowed_origins if o not in unsafe]
    if not allowed_origins and not is_production:
        allowed_origins = ["http://localhost:5173"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],   # 내려받기 파일 이름을 FE 가 읽도록
    )

    # 세션 — 기본 7일, 요청마다 재서명되어 슬라이딩 갱신. SESSION_MAX_AGE_SEC 로 override.
    # TODO: 계정 모델이 생기면 비활성 계정 세션을 비우는 가드 미들웨어를 이보다 먼저 등록한다 (DESIGN.md §5)
    session_kwargs = {
        "secret_key": os.getenv("SESSION_SECRET_KEY"),
        "max_age": int(os.getenv("SESSION_MAX_AGE_SEC", str(86400 * 7))),
    }
    if is_production:
        session_kwargs["same_site"] = "none"
        session_kwargs["https_only"] = True
    app.add_middleware(SessionMiddleware, **session_kwargs)


# ────────────────────────────────────────────
# 프로젝트 경로 상수
# ────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
