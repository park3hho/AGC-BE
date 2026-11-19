"""서버 자동 처리 루프 — AI 가 30분 점검에서 손으로 하던 일 중 규칙만으로 되는 것 (2026-11-19, 사용자: '서버로 규칙화할 건 규칙화').

OPS_AUTO_MINUTES(기본 10)마다 차례로:
  card   카드 결제 자동 대조 (services/ops/auto_card.py) — 항상 켬 (우리 DB 만 고침)
  claims 쿠팡 출고중지 요청 · 반품 접수 · 취소 완료인데 출고중지 미처리 감지 → AI 알림 (auto_claims.py, 30분마다, 처리는 안 함)
마켓에 쓰는 일(네이버 발송지연 · 송장 발송처리)은 고객에게 보이므로 따로 스위치(기본 꺼짐)로 단다.
최근 결과는 LAST 에 두고 GET /ops/auto 로 본다."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
MINUTES = int(os.getenv("OPS_AUTO_MINUTES", "10") or 0)
LAST: dict[str, dict] = {}


async def _job(name: str, fn) -> None:
    started = datetime.now(KST)
    try:
        res = await fn()
        LAST[name] = {"at": started.strftime("%Y-%m-%d %H:%M"), "ok": True, "result": res}
    except Exception as e:
        logger.exception(f"자동 처리 실패: {name}")
        LAST[name] = {"at": started.strftime("%Y-%m-%d %H:%M"), "ok": False, "error": type(e).__name__}


async def run_all() -> dict:
    from services.ops import auto_card, auto_claims
    await _job("card", auto_card.run_once)
    await _job("claims", auto_claims.run_once)
    return LAST


async def ops_auto_loop() -> None:
    if MINUTES <= 0:
        return
    await asyncio.sleep(90)          # 서버 기동 직후 몰리지 않게
    while True:
        await run_all()
        await asyncio.sleep(MINUTES * 60)