"""위안 환율 — 가격 책정 · 배송비가 같이 쓰는 하나의 값.

하루 1건 (`exchange_rate.date` unique, KST 날짜). "현재 환율" = 날짜 최근 행. 한 건도 없으면 DEFAULT_FX_RATE (200).
- 자동: 서버가 켜질 때 + 매시간 하나은행 고시(안 되면 open.er-api)를 받아 오늘 값을 갱신 (fx_auto_loop).
- 직접 입력: 환율 설정 화면. 그날은 자동으로 덮어쓰지 않는다 ('지금 받아오기'를 누르면 바뀜).
"""

import asyncio
import logging
from decimal import Decimal
from typing import Optional

from tortoise.exceptions import IntegrityError

from core.pricing_config import DEFAULT_FX_RATE, FX_AUTO_INTERVAL_SEC, FX_HISTORY_SIZE, FxSource
from models.product.pricing import ExchangeRate
from services.pricing.fx_fetch import fetch_cny_krw
from utils.code_gen import today_kst

logger = logging.getLogger(__name__)


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
    async def overview() -> dict:
        rows = await ExchangeRate.all().order_by("-date", "-id").limit(FX_HISTORY_SIZE)
        return {
            "current": _rate_dict(rows[0] if rows else None),
            "history": [_rate_dict(r) for r in rows],
        }

    @staticmethod
    async def _upsert_today(cny_krw: Decimal, source: FxSource) -> None:
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
            await ExchangeRateService._upsert_today(fetched["cny_krw"], FxSource(fetched["source"]))
        return {
            "updated": updated,          # False = 오늘 직접 입력한 값이 있어 그대로 둠
            "fetched": {
                "cny_krw": fx_str(fetched["cny_krw"]),
                "source": fetched["source"],
                "observed_at": fetched["observed_at"],
            },
        }


async def fx_auto_loop() -> None:
    """서버가 켜지면 바로, 그 뒤 FX_AUTO_INTERVAL_SEC 마다 오늘 환율을 받는다 (main.py lifespan 에서 시작).
    실패해도 멈추지 않는다 — 마지막 저장값으로 계속 계산되고 다음 차례에 다시 한다."""
    while True:
        try:
            r = await ExchangeRateService.refresh(force=False)
            logger.info(
                f"환율 자동 받기: {r['fetched']['cny_krw']} ({r['fetched']['source']})"
                + ("" if r["updated"] else " — 오늘 직접 입력값이 있어 저장 안 함")
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"환율 자동 받기 실패: {type(e).__name__}: {e}")
        await asyncio.sleep(FX_AUTO_INTERVAL_SEC)
