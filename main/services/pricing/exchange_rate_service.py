"""위안 환율 — 가격 책정 · 배송비가 같이 쓰는 하나의 값.

하루 1건 (`exchange_rate.date` unique, KST 날짜). "현재 환율" = 날짜 최근 행. 한 건도 없으면 DEFAULT_FX_RATE (200).
- 자동: 매일 오전 9시(KST) 하나은행 고시(안 되면 open.er-api)를 받아 오늘 값으로 저장 (fx_auto_loop).
- 직접 입력: 환율 설정 화면. 그날은 자동으로 덮어쓰지 않는다 ('지금 받아오기'를 누르면 바뀜).
- 저장할 때마다 exchange_rate_log 에 한 줄씩 남긴다 — 추이 그래프는 이 서버 기록만 쓴다 (외부 과거 데이터 안 받음).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from tortoise.exceptions import IntegrityError

from core.pricing_config import (
    DEFAULT_FX_RATE,
    FX_DAILY_HOUR,
    FX_DAILY_MINUTE,
    FX_RETRY_MAX,
    FX_RETRY_SEC,
    FX_HISTORY_SIZE,
    FX_TREND_DAILY_AFTER_DAYS,
    FX_TREND_MAX_DAYS,
    FxSource,
)
from models.product.pricing import ExchangeRate, ExchangeRateLog
from services.pricing.fx_fetch import fetch_cny_krw
from utils.code_gen import today_kst

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))


def fx_str(v) -> str:
    """환율은 소수 4자리 문자열 ("200.0000") — price_cny 처럼 소수 오차를 막는다."""
    return format(Decimal(str(v)), ".4f")


def _rate_dict(row: Optional[ExchangeRate]) -> dict:
    if row is None:
        return {"cny_krw": fx_str(DEFAULT_FX_RATE), "date": None, "source": FxSource.DEFAULT.value, "updated_at": None}
    return {
        "cny_krw": fx_str(row.cny_krw),
        "date": row.date.isoformat(),
        "source": row.source,
        "updated_at": row.updated_at.isoformat(),
    }


class ExchangeRateService:
    @staticmethod
    async def current() -> dict:
        row = await ExchangeRate.all().order_by("-date", "-id").first()
        return _rate_dict(row)

    @staticmethod
    async def current_rate() -> Decimal:
        """계산용 숫자 — current() 의 cny_krw."""
        return Decimal((await ExchangeRateService.current())["cny_krw"])

    @staticmethod
    async def overview(days: Optional[int] = None) -> dict:
        """현재 환율 + 날짜별 기록(최근 FX_HISTORY_SIZE 일).
        days 를 주면 trend 도 준다 — 최근 days 일 동안 서버가 저장한 기록 (exchange_rate_log, 오래된 → 최근).
        FX_TREND_DAILY_AFTER_DAYS 일보다 길면 하루 마지막 값 하나씩으로 줄인다."""
        rows = await ExchangeRate.all().order_by("-date", "-id").limit(FX_HISTORY_SIZE)
        out = {
            "current": _rate_dict(rows[0] if rows else None),
            "history": [_rate_dict(r) for r in rows],
        }
        if days:
            days = min(days, FX_TREND_MAX_DAYS)
            since = datetime.now(timezone.utc) - timedelta(days=days)
            logs = await ExchangeRateLog.filter(created_at__gte=since).order_by("created_at", "id")
            if days > FX_TREND_DAILY_AFTER_DAYS:
                last_of_day = {}
                for log in logs:
                    last_of_day[log.created_at.astimezone(KST).date()] = log
                logs = list(last_of_day.values())
            out["trend"] = [
                {"at": log.created_at.isoformat(), "cny_krw": fx_str(log.cny_krw), "source": log.source}
                for log in logs
            ]
        return out
    @staticmethod
    async def _upsert_today(cny_krw: Decimal, source: FxSource, observed_at: Optional[str] = None) -> None:
        await ExchangeRateLog.create(cny_krw=cny_krw, source=source.value, observed_at=observed_at)
        day = today_kst()
        for _ in range(2):
            row = await ExchangeRate.get_or_none(date=day)
            if row:
                row.cny_krw = cny_krw
                row.source = source.value
                await row.save(update_fields=["cny_krw", "source", "updated_at"])
                return
            try:
                await ExchangeRate.create(date=day, cny_krw=cny_krw, source=source.value)
                return
            except IntegrityError:
                continue    # 같은 날 첫 저장이 동시에 겹침 → 다시 읽어서 덮어쓴다

    @staticmethod
    async def set_manual(cny_krw: Decimal) -> dict:
        """오늘(KST) 환율을 직접 넣는다. 오늘 값이 이미 있으면 덮어쓴다. 그날은 자동으로 덮어쓰지 않는다."""
        await ExchangeRateService._upsert_today(cny_krw, FxSource.MANUAL)
        return await ExchangeRateService.current()

    @staticmethod
    async def refresh(force: bool) -> dict:
        """환율을 받아와 오늘(KST) 값으로 저장한다 (fx_fetch — 못 받으면 FxFetchError).
        force=False(자동): 오늘 직접 입력한 값이 있으면 그대로 둔다.
        force=True(화면의 '지금 받아오기'): 직접 입력한 값도 받은 값으로 바꾼다."""
        fetched = await fetch_cny_krw()
        today = await ExchangeRate.get_or_none(date=today_kst())
        updated = force or not (today and today.source == FxSource.MANUAL.value)
        if updated:
            await ExchangeRateService._upsert_today(
                fetched["cny_krw"], FxSource(fetched["source"]), str(fetched["observed_at"] or "")[:40] or None
            )
        return {
            "updated": updated,          # False = 오늘 직접 입력한 값이 있어 그대로 둠
            "fetched": {
                "cny_krw": fx_str(fetched["cny_krw"]),
                "source": fetched["source"],
                "observed_at": fetched["observed_at"],
            },
        }


def _next_daily_run(now: datetime) -> datetime:
    run = now.replace(hour=FX_DAILY_HOUR, minute=FX_DAILY_MINUTE, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


async def _refresh_with_retry() -> None:
    """자동 받기 한 번 — 실패하면 FX_RETRY_SEC 뒤 다시, 최대 FX_RETRY_MAX 번. 그래도 안 되면 마지막 저장값으로 계속."""
    for attempt in range(1, FX_RETRY_MAX + 1):
        try:
            r = await ExchangeRateService.refresh(force=False)
            logger.info(
                f"환율 자동 받기: {r['fetched']['cny_krw']} ({r['fetched']['source']})"
                + ("" if r["updated"] else " — 오늘 직접 입력값이 있어 저장 안 함")
            )
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"환율 자동 받기 실패 ({attempt}/{FX_RETRY_MAX}): {type(e).__name__}: {e}")
            if attempt < FX_RETRY_MAX:
                await asyncio.sleep(FX_RETRY_SEC)


async def fx_auto_loop() -> None:
    """매일 FX_DAILY_HOUR:FX_DAILY_MINUTE(KST, 오전 9시)에 오늘 환율을 한 번 받아 저장한다 (main.py lifespan 에서 시작).
    서버가 켜질 때: 오늘 값이 아직 없고, 9시가 지났거나 저장된 환율이 하나도 없으면 바로 받는다
    (9시 전에 켜지면 9시까지 어제 값을 쓴다). 주말·공휴일엔 직전 영업일 고시가 그대로 저장된다."""
    now = datetime.now(KST)
    if not await ExchangeRate.exists(date=now.date()):
        past = (now.hour, now.minute) >= (FX_DAILY_HOUR, FX_DAILY_MINUTE)
        if past or not await ExchangeRate.exists():
            await _refresh_with_retry()
    while True:
        now = datetime.now(KST)
        await asyncio.sleep((_next_daily_run(now) - now).total_seconds())
        await _refresh_with_retry()