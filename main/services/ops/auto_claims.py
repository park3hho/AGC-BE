"""쿠팡 취소·출고중지 감지 — 처리해야 할 클레임을 서버가 찾아 AI 알림으로 남긴다 (2026-11-19).

30분 점검이 매 회차 손으로 보던 것(ops-check.md 9단계)을 서버가 본다. 처리(승인·거부)는 하지 않는다 —
중국 출고 여부에 따라 승인/반품 전환이 갈리므로 AI·사람이 정한다. 여기서는 '남아 있는 것'만 알린다.

CLAIMS_EVERY_MIN(기본 30)마다 쿠팡 반품/취소 요청 최근 30일 (market_clients.coupang_claims):
  stop      RU 출고중지요청 — 판매자 처리 전
  return    UC 반품접수
  unrel     CC 완료인데 releaseStopStatus '미처리' — Wing 출고중지 목록에 남아 있음 (API RU 에는 안 나옴, 11-13 누락 사고)
알림: kind claim · level action · key claim:coupang:{receiptId}:{stop|return|unrel}
      본문에 주문 코드 · 사유 · 지금 중국/집운 상태(타오바오 구매 cn_status · 집운 출고 여부)를 붙인다.
처리돼서 목록에서 빠지면(같은 receipt 가 처리(출고중지)·처리(이미출고) 등) 그 알림을 끝남으로 (resolve_key)."""

import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
EVERY = timedelta(minutes=int(os.getenv("CLAIMS_EVERY_MIN", "30") or 30))
LOOKBACK = timedelta(days=30)
UNRELEASED = "미처리"
LABEL = {"stop": "쿠팡 출고중지 요청", "return": "쿠팡 반품 접수", "unrel": "쿠팡 취소 완료 · 출고중지 미처리"}
_last = {"at": None}


def _pending(rc: dict) -> str | None:
    claim = rc.get("_claim")
    if claim == "STOP_SHIPPING":
        return "stop"
    if claim == "RETURN":
        return "return"
    if claim == "DONE" and str(rc.get("releaseStopStatus") or "").strip() == UNRELEASED:
        return "unrel"
    return None


async def _state_text(order_ids: list[int]) -> str:
    """주문들의 중국·집운 상태 한 줄 — 승인해도 되는지(출고 전) 판단 근거."""
    from models.order.jiyun import JiyunShipment
    from models.order.purchase import TaobaoPurchase

    parts = []
    for p in await TaobaoPurchase.filter(order_id__in=order_ids, deleted_at=None):
        parts.append(f"타오바오 {p.cn_status}" + (" · 창고 입고" if p.arrived_at else ""))
    for j in await JiyunShipment.filter(order_id__in=order_ids, deleted_at=None):
        parts.append(f"집운 {j.status}" + (" · 중국 출고됨" if j.dispatched_at else ""))
    return " / ".join(parts) or "구매 기록 없음 (중국 출고 전)"


async def run_once(force: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    if not force and _last["at"] and now - _last["at"] < EVERY:
        return {"skipped": "interval"}
    _last["at"] = now

    from models.order.order import MarketOrder
    from services.order import market_clients as mc

    try:
        from services.ops.alerts import raise_alert, resolve_key
        from models.ops.alert import AgentAlert   # noqa: F401  (있는지만 확인)
    except ImportError:
        raise_alert = resolve_key = None

    receipts = await mc.coupang_claims(now - LOOKBACK, now)
    pending_keys, out = set(), {"receipts": len(receipts), "pending": [], "new": 0, "resolved": 0}
    for rc in receipts:
        tag = _pending(rc)
        if not tag:
            continue
        rid = rc.get("receiptId")
        key = f"claim:coupang:{rid}:{tag}"
        pending_keys.add(key)
        orders = await MarketOrder.filter(market="coupang", order_no=str(rc.get("orderId") or "")).values("id", "code", "is_test")
        codes = sorted({o["code"] for o in orders if o["code"]})
        out["pending"].append({"receipt": rid, "tag": tag, "orders": codes})
        if not raise_alert:
            continue
        state = await _state_text([o["id"] for o in orders])
        reason = " · ".join(x for x in (rc.get("cancelReasonCategory1"), rc.get("cancelReasonCategory2"), rc.get("cancelReason")) if x)
        created = rc.get("createdAt") or ""
        body = (f"접수 {created[:16].replace('T', ' ')} · receiptId {rid} · {rc.get('receiptStatus') or ''}"
                f"{' · 출고중지 ' + str(rc.get('releaseStopStatus')) if rc.get('releaseStopStatus') else ''}"
                f"{' · 사유 ' + reason if reason else ''}\n지금 상태: {state}\n"
                "중국 출고 전이면 출고중지 승인, 이미 출고면 승인 말고 반품 전환/보고 (ops-check.md 9단계)")
        try:
            r = await raise_alert(key=key, kind="claim", level="action",
                                  title=f"{LABEL[tag]} — {', '.join(codes) or rc.get('orderId')}",
                                  body=body[:1000], order_codes=codes, target=f"coupang:{rid}", source="auto:claims")
            if r.get("new"):
                out["new"] += 1
        except Exception:
            logger.exception("클레임 알림 기록 실패")
    # 처리돼서 사라진 것 — 열린 claim:coupang:* 알림 끝내기
    if resolve_key:
        try:
            from models.ops.alert import AgentAlert
            for a in await AgentAlert.filter(key__startswith="claim:coupang:", resolved_at=None, source="auto:claims"):
                if a.key not in pending_keys:
                    await resolve_key(a.key)
                    out["resolved"] += 1
        except Exception:
            logger.exception("클레임 알림 끝내기 실패")
    return out
