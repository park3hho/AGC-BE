import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from tortoise.contrib.fastapi import RegisterTortoise

from core.config import UPLOAD_DIR, UPLOAD_URL_PREFIX, setup_middlewares
from core.response_utils import success
from database import TORTOISE_ORM
from services.pricing.exchange_rate_service import fx_auto_loop
from routers import (
    auth,
    company_account,
    exchange_rate,
    health,
    price_survey,
    pricing,
    product,
    shipping,
    upload,
    users,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Tortoise 1.x: Tortoise.init() 만 하면 요청 핸들러에서 연결이 안 보인다
    #   ("No TortoiseContext is currently active"). FastAPI 연동은 RegisterTortoise 로 한다.
    async with RegisterTortoise(app, config=TORTOISE_ORM):
        # 환율 자동 받기 — DB 연결이 살아 있는 동안만 돈다 (core/pricing_config.FX_AUTO_INTERVAL_SEC)
        fx_task = asyncio.create_task(fx_auto_loop())
        try:
            yield
        finally:
            fx_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await fx_task


# API 문서(Swagger·ReDoc·openapi.json)는 기본 비공개. dev 에서는 .env 에 ENABLE_DOCS=1.
#   ⚠️ .env 변경은 docker compose restart 로 반영되지 않는다 — up -d (재생성) 필요.
_DOCS_ON = os.getenv("ENABLE_DOCS", "").strip().lower() in ("1", "true", "yes")
app = FastAPI(
    title="AGC API",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS_ON else None,
    redoc_url="/redoc" if _DOCS_ON else None,
    openapi_url="/openapi.json" if _DOCS_ON else None,
)
setup_middlewares(app)

# 라우터는 각 파일의 APIRouter(prefix=..., tags=...) 에서 경로를 정한다 — 여기서는 등록만
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(company_account.router)
app.include_router(product.router)
app.include_router(price_survey.router)
app.include_router(pricing.router)
app.include_router(exchange_rate.router)
app.include_router(shipping.router)
app.include_router(upload.router)

# 업로드된 사진 내려주기 — /files/photos/2026/10/xxx.jpg
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount(UPLOAD_URL_PREFIX, StaticFiles(directory=UPLOAD_DIR), name="files")


@app.get("/")
def home():
    return success(message="AGC API Online")
