"""통관 진행 조회 — 관세청 UNI-PASS API001 화물통관진행정보 (cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo) (2026-10-29).

집운 기록에 H B/L 이 들어간 출고 건을 자동 수집 때 같이 조회해 jiyun_shipment.customs_* 에 적는다.
- 조회되면(tCnt ≥ 1) 통관 진행 중 — customs_status = 관세청 통관진행상태 (예: 입항, 반입신고, 수입신고, 수입신고수리)
- 수입신고수리 · 반출신고가 나오면 통관 완료 (customs_cleared_at)
자사몰 고객 화면은 이 칸으로 '통관 중 → 통관 완료' 를 보여 준다."""

import asyncio
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from models.order.jiyun import JiyunShipment
from services.hq_client import UNIPASS, credential_values  # 키 정본 = HQ (2026-10-30)

logger = logging.getLogger(__name__)
URL = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
SERVICE = UNIPASS  # HQ API 키 code
KEY_LABEL = "API001 인증키 (화물통관진행)"
KST = timezone(timedelta(hours=9))
CLEARED = ("수입신고수리", "반출신고", "반출")
RECHECK = timedelta(minutes=30)
GIVE_UP = timedelta(days=30)          # 출고 뒤 30일이 지나도 완료가 안 보이면 더 묻지 않는다


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def _t(el, tag):
    x = el.find(tag) if el is not None else None
    return (x.text or "").strip() if x is not None and x.text else ""


def _dt(s: str):
    s = "".join(c for c in s if c.isdigit())
    try:
        return datetime.strptime(s[:14], "%Y%m%d%H%M%S").replace(tzinfo=KST) if len(s) >= 14 else None
    except ValueError:
        return None


async def cargo_progress(hbl: str, year: int) -> dict:
    """반환 {found, status, cleared, cleared_at, steps:[{name, at}]} · 조회 실패면 예외."""
    _, secrets = await credential_values(SERVICE)
    key = secrets.get(KEY_LABEL)
    if not key:
        raise RuntimeError("UNI-PASS API001 인증키가 없습니다.")
    q = urllib.parse.urlencode({"crkyCn": key, "hblNo": hbl.strip().upper(), "blYy": str(year)})
    root = ET.fromstring(await asyncio.to_thread(_get, f"{URL}?{q}"))
    cnt = int(_t(root, "tCnt") or 0)
    if cnt < 0:
        raise RuntimeError("UNI-PASS 응답 오류 " + "; ".join(e.text or "" for e in root.iter("ntceInfo"))[:200])
    if cnt == 0:
        return {"found": False, "status": None, "cleared": False, "cleared_at": None, "steps": []}
    vo = root.find("cargCsclPrgsInfoQryVo")
    status = _t(vo, "csclPrgsStts") or _t(vo, "prgsStts")
    steps = [{"name": _t(d, "cargTrcnRelaBsopTpcd"), "at": _dt(_t(d, "prcsDttm"))} for d in root.iter("cargCsclPrgsInfoDtlQryVo")]
    done = [s for s in steps if any(c in s["name"] for c in CLEARED)]
    cleared = bool(done) or any(c in status for c in CLEARED)
    cleared_at = min((s["at"] for s in done if s["at"]), default=None) or (_dt(_t(vo, "prcsDttm")) if cleared else None)
    return {"found": True, "status": status, "cleared": cleared, "cleared_at": cleared_at, "steps": steps}


async def refresh_customs(force: bool = False) -> int:
    """H B/L 이 있는 출고 건 중 통관 완료 전인 것을 조회. 반환 = 바뀐 건수."""
    now = datetime.now(timezone.utc)
    qs = JiyunShipment.filter(deleted_at=None, status="dispatched", hbl__isnull=False, customs_cleared_at=None)
    n = 0
    for j in await qs:
        if not j.hbl:
            continue
        if not force and j.customs_checked_at and now - j.customs_checked_at < RECHECK:
            continue
        if j.dispatched_at and now - j.dispatched_at > GIVE_UP:
            continue
        year = (j.dispatched_at or now).astimezone(KST).year
        try:
            r = await cargo_progress(j.hbl, year)
        except Exception as e:
            logger.warning(f"통관 조회 실패: jiyun={j.id} {type(e).__name__} {str(e)[:150]}")
            continue
        changed = r["found"] and (r["status"] != j.customs_status or (r["cleared"] and not j.customs_cleared_at))
        j.customs_checked_at = now
        if r["found"]:
            j.customs_status = (r["status"] or "조회됨")[:40]
            if r["cleared"]:
                j.customs_cleared_at = r["cleared_at"] or now
        await j.save(update_fields=["customs_checked_at", "customs_status", "customs_cleared_at", "updated_at"])
        n += int(bool(changed))
    return n
