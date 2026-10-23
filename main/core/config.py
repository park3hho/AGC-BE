# core/config.py
# FastAPI 미들웨어 설정 (CORS, Session) + 프로젝트 경로 상수

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.session import SessionMiddleware

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

    # 세션 — 기본 7일. 로그인이 필요한 요청마다 다시 써서 슬라이딩 갱신 (core/auth_deps.py). SESSION_MAX_AGE_SEC 로 override.
    #   로그인 유지를 안 고르면 Max-Age 없는 브라우저 세션 쿠키 (core/session.py).
    #   비활성 계정·비밀번호 변경 세션 차단은 미들웨어가 아니라 require_auth 가 매 요청 DB 확인으로 한다.
    session_kwargs = {
        "secret_key": os.getenv("SESSION_SECRET_KEY"),
        "max_age": int(os.getenv("SESSION_MAX_AGE_SEC", str(86400 * 7))),
    }
    if is_production:
        # FE 가 Vercel rewrite(/api → BE)로 같은 출처에서 부르면 lax 로 충분 (CSRF 에 더 안전).
        #   FE 가 다른 도메인에서 BE 를 직접 부르게 되면 SESSION_SAME_SITE=none.
        session_kwargs["same_site"] = os.getenv("SESSION_SAME_SITE", "none").strip().lower() or "none"
        session_kwargs["https_only"] = True
    app.add_middleware(SessionMiddleware, **session_kwargs)


# ────────────────────────────────────────────
# 프로젝트 경로 상수
# ────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# 업로드 파일 — 이 PC 디스크. compose 가 ./uploads 를 /uploads 로 연결한다 (컨테이너를 지워도 남는다)
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))
UPLOAD_URL_PREFIX = "/files"      # 저장된 파일은 이 주소 아래로 내려준다 (main.py StaticFiles)

# 공개하면 안 되는 파일 (회사 서류 — 주민번호·계좌가 들어 있음). /files 로 내려주지 않고 API 가 권한 확인 후 내려준다.
# compose 가 ./private 를 /private 로 연결한다 (BE/private, 커밋 금지)
PRIVATE_DIR = Path(os.getenv("PRIVATE_DIR", str(BASE_DIR.parent / "private")))
