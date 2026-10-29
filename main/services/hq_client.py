"""HQ (회사 정보 정본 — eido-hq) 서비스 API 클라이언트 (2026-10-30).

회사 계정·API 키·기본 정보의 정본은 HQ 로 옮겼다. AGC 는 값을 저장하지 않고 HQ /svc 에서 읽는다.
  - 주소·키: .env HQ_URL (예: http://hq_app:8000/svc — 같은 PC Docker 네트워크 안에서만) · HQ_SERVICE_KEY (헤더 X-Service-Key)
  - 설명서: C:\\Users\\iwill\\HQ\\docs\\svc-api.md
  - 값(키·비밀값)은 로그·응답·커밋에 넣지 않는다. 실패 로그에는 경로와 오류 종류만.

장애 대비 (HQ 설명서 '장애 대비'):
  - 받은 값은 메모리에만 들고 있다 (디스크·DB 사본 금지). CACHE_TTL_SEC 안에는 HQ 를 다시 부르지 않는다
    → 5분마다 도는 주문 수집이 매번 HQ 열람 기록을 남기지 않게.
  - HQ 가 실패하면(꺼짐·시간 초과·5xx·키 오류) 마지막으로 받은 값으로 계속 돈다. 한 번도 못 받았으면 503.
  - 서버를 다시 켜면 메모리 값은 사라진다 → 그때 HQ 가 꺼져 있으면 첫 호출이 503.
"""

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import HTTPException

logger = logging.getLogger(__name__)

CACHE_TTL_SEC = 600          # 10분 — 이 안에는 메모리 값을 그대로 쓴다
TIMEOUT_SEC = 10

# 고정 코드 (HQ API 키 code) — label 은 옛 AGC 와 같다
NAVER_COMMERCE = "naver_commerce"
COUPANG_OPENAPI = "coupang_openapi"
UNIPASS = "unipass"

_cache: dict[str, tuple[float, object]] = {}   # key → (받은 시각, 값)
_locks: dict[str, asyncio.Lock] = {}


class HqNotFound(Exception):
    """HQ 에 없거나 AGC 에 공유되지 않음 (404)."""


def _get(path: str) -> dict:
    base = os.getenv("HQ_URL", "").rstrip("/")
    key = os.getenv("HQ_SERVICE_KEY", "")
    if not base or not key:
        raise RuntimeError("HQ_URL · HQ_SERVICE_KEY 가 설정되지 않았습니다.")
    req = urllib.request.Request(base + path, headers={"X-Service-Key": key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise HqNotFound(path) from None
        raise RuntimeError(f"HQ {e.code}") from None


async def _cached(key: str, path: str, pick):
    """TTL 안이면 메모리 값, 아니면 HQ. HQ 실패면 마지막 값 (없으면 예외 그대로)."""
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_SEC:
        return hit[1]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL_SEC:
            return hit[1]
        try:
            val = pick(await asyncio.to_thread(_get, path))
        except Exception as e:
            if hit:
                reason = str(e) if isinstance(e, RuntimeError) else type(e).__name__   # RuntimeError 는 "HQ 503" 처럼 값 없는 문구뿐
                logger.warning("HQ 조회 실패 — 마지막 값으로 계속 (%s, %s)", key, reason)
                return hit[1]
            raise
        _cache[key] = (time.monotonic(), val)
        return val


def invalidate(prefix: str = "") -> None:
    """메모리 값 버리기 — 키를 HQ 에서 바꾼 직후 바로 반영하고 싶을 때."""
    for k in [k for k in _cache if k.startswith(prefix)]:
        _cache.pop(k, None)


async def credential_values(code: str) -> tuple[dict, dict]:
    """서버 안에서 외부 API 를 부를 때만 — (공개값 {label: value}, 비밀값 {label: 평문}).
    HQ GET /api-credentials/by-code/{code}/values. 반환값을 응답·로그에 넣지 말 것."""
    try:
        return await _cached(
            f"cred:{code}",
            f"/api-credentials/by-code/{urllib.parse.quote(code)}/values",
            lambda d: (dict(d["credential"].get("public") or {}), dict(d["credential"].get("secrets") or {})),
        )
    except HqNotFound:
        raise HTTPException(status_code=503, detail=f"HQ 에 '{code}' API 키가 없거나 AGC 에 공유되지 않았습니다.")
    except Exception as e:
        logger.error("HQ API 키 조회 실패 (%s): %s", code, type(e).__name__)
        raise HTTPException(status_code=503, detail=f"HQ 에서 '{code}' API 키를 받지 못했습니다.")


async def linked_value(link: str) -> str | None:
    """HQ 기본 정보 중 앱 연결(link)이 붙은 항목의 값 — GET /company-info/by-link/{link}.
    붙은 항목이 없으면 None, 있는데 값이 비었으면 ''. HQ 가 안 되고 마지막 값도 없으면 None (화면이 '연결 없음'으로 보임)."""

    def pick(d):
        i = d.get("info")
        return None if i is None else (i.get("value") or "")

    key = f"link:{link}"
    try:
        return await _cached(key, f"/company-info/by-link/{urllib.parse.quote(link)}", pick)
    except HqNotFound:
        _cache[key] = (time.monotonic(), None)
        return None
    except Exception as e:
        logger.error("HQ 기본 정보 조회 실패 (%s): %s", link, type(e).__name__)
        return None


HQ_WEB_URL = os.getenv("HQ_WEB_URL", "https://eido-hq.vercel.app")   # 사람이 고치는 HQ 화면


async def reminders() -> dict:
    """홈 할 일용 — HQ API 키(AGC 에 공유된 것)·기본 정보의 만료·재인증 날짜만. 비밀값·값·파일은 안 담는다.
    목록 조회라 HQ 열람 기록은 남지 않는다. HQ 가 안 되면 마지막 값, 그것도 없으면 빈 목록 + ok=False."""

    def creds(d):
        return [{"id": c["id"], "service": c["service"], "expires_on": c.get("expires_on"),
                 "reauth_from": c.get("reauth_from"), "reauth_to": c.get("reauth_to")} for c in d.get("items", [])]

    def infos(d):
        return [{"id": i["id"], "category": i["category"], "name": i["name"],
                 "expires_on": i.get("expires_on"), "remind": i.get("remind", True)} for i in d.get("items", [])]

    out = {"hq_url": HQ_WEB_URL, "ok": True, "api_credentials": [], "company_info": []}
    for key, path, pick, field in (("list:cred", "/api-credentials", creds, "api_credentials"),
                                   ("list:info", "/company-info", infos, "company_info")):
        try:
            out[field] = await _cached(key, path, pick)
        except Exception as e:
            logger.error("HQ 목록 조회 실패 (%s): %s", path, type(e).__name__)
            out["ok"] = False
    return out
