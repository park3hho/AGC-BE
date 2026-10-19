"""위안 환율 — 가격 책정 · 배송비가 같이 쓰는 하나의 값.

지금은 사람이 직접 넣는다 (환율 설정 화면). 하루 1건 (`exchange_rate.date` unique, KST 날짜) — 같은 날 다시 넣으면 덮어쓴다.
"현재 환율" = 날짜 최근 행. 한 건도 없으면 DEFAULT_FX_RATE (200).
나중에 환율 API 를 붙이면 같은 테이블에 source 를 API 이름으로 넣는다.
"""

from decimal import Decimal
from typing import Optional

from tortoise.exceptions import IntegrityError

from core.pricing_config import DEFAULT_FX_RATE, FX_HISTORY_SIZE, FxSource
from models.product.pricing import ExchangeRate
from utils.code_gen import today_kst


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
    async def set_manual(cny_krw: Decimal) -> dict:
        """오늘(KST) 환율을 직접 넣는다. 오늘 값이 이미 있으면 덮어쓴다."""
        day = today_kst()
        for _ in range(2):
            row = await ExchangeRate.get_or_none(date=day)
            if row:
                row.cny_krw = cny_krw
                row.source = FxSource.MANUAL.value
                await row.save(update_fields=["cny_krw", "source", "updated_at"])
                break
            try:
                await ExchangeRate.create(date=day, cny_krw=cny_krw, source=FxSource.MANUAL.value)
                break
            except IntegrityError:
                continue    # 같은 날 첫 저장이 동시에 겹침 → 다시 읽어서 덮어쓴다
        return await ExchangeRateService.current()
