"""위안 환율 받아오기 — 하나은행 고시 매매기준율이 먼저, 안 되면 open.er-api (core/pricing_config.FX_*).

    await fetch_cny_krw()  → {"cny_krw": Decimal("198.5800"), "source": "hana", "observed_at": "2026-10-21T08:46:54+09:00"}

표준 라이브러리 urllib 만 쓴다 (의존성 추가 없음, DESIGN.md §1). 블로킹 호출이라 스레드에서 돌린다.
둘 다 실패하면 FxFetchError — 부르는 쪽은 마지막 저장값으로 계속 계산한다.
"""

import asyncio
import json
import logging
import urllib.request
from decimal import Decimal

from core.pricing_config import (
    FX_FETCH_TIMEOUT_SEC,
    FX_HANA_URL,
    FX_OPEN_ER_URL,
    FX_SANE_MAX,
    FX_SANE_MIN,
    FxSource,
)

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (AGC fx-fetch)", "Accept": "application/json"}


class FxFetchError(Exception):
    """모든 환율 출처에서 받지 못함."""


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=FX_FETCH_TIMEOUT_SEC) as res:
        return json.loads(res.read().decode("utf-8"))


def _hana() -> tuple[Decimal, str | None]:
    """하나은행 고시 매매기준율 (네이버 금융 데이터) — 하루 여러 회차, 원/위안."""
    data = _get_json(FX_HANA_URL)
    if not data.get("isSuccess"):
        raise ValueError(f"응답 실패: {data.get('message')}")
    result = data["result"]
    return Decimal(str(result["closePrice"]).replace(",", "")), result.get("localTradedAt")


def _open_er() -> tuple[Decimal, str | None]:
    """open.er-api — 하루 1번 갱신되는 공개 환율 (예비)."""
    data = _get_json(FX_OPEN_ER_URL)
    if data.get("result") != "success":
        raise ValueError(f"응답 실패: {data.get('error-type')}")
    return Decimal(str(data["rates"]["KRW"])), data.get("time_last_update_utc")


_SOURCES = ((FxSource.HANA, _hana), (FxSource.OPEN_ER, _open_er))


async def fetch_cny_krw() -> dict:
    errors = []
    for source, fn in _SOURCES:
        try:
            rate, observed_at = await asyncio.to_thread(fn)
            if not (FX_SANE_MIN <= rate <= FX_SANE_MAX):
                raise ValueError(f"값이 이상함: {rate}")
            return {
                "cny_krw": rate.quantize(Decimal("0.0001")),
                "source": source.value,
                "observed_at": observed_at,
            }
        except Exception as e:  # 다음 출처로 — 어느 출처가 왜 실패했는지만 남긴다
            logger.warning(f"환율 받기 실패 ({source.value}): {type(e).__name__}: {e}")
            errors.append(source.value)
    raise FxFetchError(f"모든 환율 출처 실패: {', '.join(errors)}")
