"""국내 배송 기록 — 국내 택배 송장 1개 = 1건. 고객 주문(MarketOrder) 1건에 붙는다 (2026-11-03).

만드는 곳 (자동)
- 집운 기록에 국내 송장(kr_tracking_no)이 들어가면 → sync_jiyun (source=jiyun)
- 마켓 원본(네이버 delivery.trackingNumber · 쿠팡 invoiceNumber)에 송장이 보이면 → refresh_domestic (source=market)
갱신 (자동 수집 5분마다, order_poll_loop)
- 마켓 발송처리: 마켓 원본의 택배사 · 송장 · 발송처리 시각
- 배송 조회: tracker.delivery (같은 송장은 30분에 한 번, 배송 완료 · 30일 지나면 그만)
- 상태: 배송 완료 > 배송 중(조회 단계 있음) > 마켓 발송처리 > 송장 나옴. problem · cancelled 는 사람이 정한 그대로 둔다

추적: 추가 · 수정 · 삭제 · 자동 갱신으로 바뀐 칸(DOMESTIC_TRACKED)마다 그 고객 주문의 OrderEvent 한 줄
(domestic_created · domestic_changed · domestic_deleted). 배송 조회 단계 자체는 기록에 남기지 않는다 (너무 많음)."""

import asyncio
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from core.domestic_config import (
    DOMESTIC_FIELD_LABEL, DOMESTIC_SOURCE, DOMESTIC_STATUS, DOMESTIC_TRACKED, MANUAL_STATUS, MARKET_DELIVERED,
    TRACK_EVENTS_MAX, TRACK_GIVE_UP, TRACK_RECHECK, TRACKER_URL,
)
from core.shipping_config import COURIERS
from models.order.domestic import DomesticShipment
from models.order.jiyun import JiyunShipment
from models.order.order import MarketOrder
from schemas.domestic import DomesticCreate, DomesticUpdate
from services.order.order_service import _dec, actor_of, log_event

logger = logging.getLogger(__name__)
SYSTEM = actor_of(None, "poller")


def alive():
    return DomesticShipment.filter(deleted_at=None)


def _iso(v):
    return v.astimezone(timezone.utc).isoformat() if isinstance(v, datetime) else v


def _dt(s):
    if not s or s in ("None", "null"):
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone(timedelta(hours=9)))
    except ValueError:
        return None


def courier_name(key):
    return COURIERS.get(key, {}).get("name") if key else None


def courier_from_market(code):
    """마켓 택배사 코드(또는 이름) → COURIERS 키. 모르면 None."""
    if not code or code in ("NONE", "None"):
        return None
    for k, v in COURIERS.items():
        if code == k or code in v["codes"].values() or code == v["name"]:
            return k
    return None


def tracking_url(courier, no):
    t = COURIERS.get(courier or "", {}).get("tracker")
    return f"https://tracker.delivery/#/{t}/{no}" if t and no else None


def market_delivery(o: MarketOrder) -> dict:
    """마켓 원본에서 발송처리 정보 — {code, tracking_no, sent_at, delivered_at, wrong}. 없으면 빈 dict."""
    if o.market not in ("naver", "coupang") or not o.raw_enc:
        return {}
    try:
        raw = json.loads(_dec(o.raw_enc))
    except Exception:
        return {}
    if o.market == "naver":
        d = raw.get("delivery") or {}
        if not d.get("trackingNumber"):
            return {}
        return {"code": d.get("deliveryCompany"), "tracking_no": str(d["trackingNumber"]).replace("-", ""),
                "sent_at": _dt(d.get("sendDate")), "delivered_at": _dt(d.get("deliveredDate")),
                "wrong": bool(d.get("isWrongTrackingNumber"))}
    no = str(raw.get("invoiceNumber") or "").replace("-", "")
    if not no:
        return {}
    return {"code": raw.get("deliveryCompanyName") or raw.get("deliveryCompanyCode"), "tracking_no": no,
            "sent_at": _dt(raw.get("inTrasitDateTime") or raw.get("inTransitDateTime")),
            "delivered_at": _dt(raw.get("deliveredDate")), "wrong": False}


async def domestic_dict(d: DomesticShipment) -> dict:
    await d.fetch_related("order")
    o = d.order
    return {
        "id": d.id,
        "order": {"id": o.id, "code": o.code, "market": o.market, "order_no": o.order_no, "market_status": o.market_status,
                  "product_name": o.product_name, "option_name": o.option_name, "quantity": o.quantity},
        "jiyun_id": d.jiyun_id, "courier": d.courier, "courier_name": courier_name(d.courier),
        "tracking_no": d.tracking_no, "tracking_url": tracking_url(d.courier, d.tracking_no),
        "status": d.status, "source": d.source, "source_label": DOMESTIC_SOURCE.get(d.source, d.source),
        "market_courier": d.market_courier, "market_courier_name": courier_name(courier_from_market(d.market_courier)),
        "market_tracking_no": d.market_tracking_no, "market_sent_at": _iso(d.market_sent_at), "market_wrong": d.market_wrong,
        "market_match": bool(d.market_tracking_no) and d.market_tracking_no == d.tracking_no,
        "track_state": d.track_state, "track_state_id": d.track_state_id, "track_location": d.track_location,
        "track_last_at": _iso(d.track_last_at), "track_events": d.track_events or [], "track_error": d.track_error,
        "tracked_at": _iso(d.tracked_at), "delivered_at": _iso(d.delivered_at), "memo": d.memo,
        "created_at": _iso(d.created_at), "updated_at": _iso(d.updated_at),
    }


def _snapshot(d: DomesticShipment) -> dict:
    return {k: _iso(getattr(d, k)) for k in DOMESTIC_TRACKED}


def _refs(d: DomesticShipment) -> dict:
    r = {"kr_courier": courier_name(d.courier), "kr_tracking_no": d.tracking_no}
    return {k: v for k, v in r.items() if v}


def _summary_of(d: DomesticShipment, changes: dict) -> str:
    head = f"국내 송장 {courier_name(d.courier) or ''} {d.tracking_no}".replace("  ", " ")
    names = [DOMESTIC_FIELD_LABEL.get(k, k) for k in changes]
    if "status" in changes:
        to = changes["status"]["to"]
        rest = [n for n in names if n != "상태"]
        return f"{head} → {DOMESTIC_STATUS.get(to, to)}" + (f" (그 밖에 {', '.join(rest)})" if rest else "")
    return f"{head} — {', '.join(names)} 수정"


def _decide_status(d: DomesticShipment, o: MarketOrder) -> str:
    if d.status in MANUAL_STATUS:
        return d.status
    if d.delivered_at or d.track_state_id == "delivered" or (o.market_status in MARKET_DELIVERED and d.market_tracking_no == d.tracking_no):
        return "delivered"
    if d.track_events:
        return "delivering"
    if d.market_tracking_no and d.market_tracking_no == d.tracking_no:
        return "dispatched"
    return "ready"


async def _log_changes(d: DomesticShipment, before: dict, actor: dict, source: str | None = None) -> None:
    after = _snapshot(d)
    changes = {k: {"from": before[k], "to": after[k]} for k in DOMESTIC_TRACKED if before[k] != after[k]}
    if not changes:
        return
    order = await MarketOrder.get(id=d.order_id)
    data = {"domestic_id": d.id, "step": "국내 배송", "stage": "done" if d.status == "delivered" else "process",
            "source": source or "domestic", "refs": _refs(d), "changes": changes}
    if "status" in changes:
        data["occurred_at"] = _iso(d.delivered_at if d.status == "delivered" else d.market_sent_at if d.status == "dispatched"
                                   else d.track_last_at) if d.status in ("delivered", "dispatched", "delivering") else None
    await log_event(order, actor, "domestic_changed", _summary_of(d, changes), data)


# ── 배송 조회 (tracker.delivery) ─────────────────────────────────────────────

def _get_json(url: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "AGC/1.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            body = {}
        return e.code, body


async def _track(d: DomesticShipment) -> None:
    """조회해서 d.track_* · delivered_at 을 채운다 (저장은 부르는 쪽)."""
    carrier = COURIERS.get(d.courier or "", {}).get("tracker")
    d.tracked_at = datetime.now(timezone.utc)
    if not carrier:
        d.track_error = "택배사를 몰라 조회하지 않았어요"
        return
    try:
        code, body = await asyncio.to_thread(_get_json, TRACKER_URL.format(carrier=carrier, no=d.tracking_no))
    except Exception as e:
        d.track_error = f"조회 실패 ({type(e).__name__})"
        return
    if code == 404:
        d.track_error = "아직 택배사에 조회되지 않아요"
        return
    if code != 200:
        d.track_error = (body.get("message") or f"조회 실패 (HTTP {code})")[:200]
        return
    events = [{"time": p.get("time"), "status": (p.get("status") or {}).get("text"),
               "status_id": (p.get("status") or {}).get("id"), "location": (p.get("location") or {}).get("name"),
               "description": p.get("description")} for p in body.get("progresses") or []]
    state = body.get("state") or {}
    last = events[-1] if events else {}
    d.track_events = events[-TRACK_EVENTS_MAX:]
    d.track_state = (state.get("text") or last.get("status") or None)
    d.track_state_id = state.get("id") or last.get("status_id")
    d.track_location = last.get("location")
    d.track_last_at = _dt(last.get("time"))
    d.track_error = None
    if d.track_state_id == "delivered" and not d.delivered_at:
        d.delivered_at = d.track_last_at or (_dt((body.get("to") or {}).get("time")))


def _due(d: DomesticShipment, now: datetime, force: bool) -> bool:
    if force:
        return True
    if d.status in ("cancelled",) or (d.status == "delivered" and d.tracked_at):
        return False
    if d.created_at and now - d.created_at > TRACK_GIVE_UP:
        return False
    return not d.tracked_at or now - d.tracked_at >= TRACK_RECHECK


async def _refresh_one(d: DomesticShipment, now: datetime, force: bool, actor: dict) -> bool:
    o = await MarketOrder.get(id=d.order_id)
    before = _snapshot(d)
    m = market_delivery(o)
    if m:
        d.market_courier, d.market_tracking_no = m["code"], m["tracking_no"]
        d.market_sent_at = m["sent_at"] or d.market_sent_at
        d.market_wrong = m["wrong"]
        if m["delivered_at"] and m["tracking_no"] == d.tracking_no:
            d.delivered_at = d.delivered_at or m["delivered_at"]
        if not d.courier and m["tracking_no"] == d.tracking_no:
            d.courier = courier_from_market(m["code"])
    tracked = _due(d, now, force)
    if tracked:
        await _track(d)
    d.status = _decide_status(d, o)
    await d.save()
    await _log_changes(d, before, actor, "tracker" if tracked else None)
    return before != _snapshot(d)


# ── 자동 생성 ───────────────────────────────────────────────────────────────

async def _upsert(order: MarketOrder, courier, tracking_no: str, source: str, actor: dict,
                  jiyun_id=None, user_id=None, memo=None) -> tuple[DomesticShipment, bool]:
    d = await alive().get_or_none(order_id=order.id, tracking_no=tracking_no)
    if d:
        changed = False
        if courier and not d.courier:
            d.courier, changed = courier, True
        if jiyun_id and not d.jiyun_id:
            d.jiyun_id, changed = jiyun_id, True
        if changed:
            before = _snapshot(d)
            await d.save()
            await _log_changes(d, before, actor)
        return d, False
    d = await DomesticShipment.create(order_id=order.id, jiyun_id=jiyun_id, courier=courier, tracking_no=tracking_no,
                                      source=source, memo=memo, created_by_id=user_id)
    await log_event(order, actor, "domestic_created",
                    f"국내 송장 {courier_name(courier) or '택배사 모름'} {tracking_no} — {DOMESTIC_SOURCE[source]}에서 등록",
                    {"domestic_id": d.id, "step": "국내 배송", "stage": "process", "source": "domestic", "refs": _refs(d),
                     "values": {k: v for k, v in _snapshot(d).items() if v not in (None, "")}})
    return d, True


async def sync_jiyun(j: JiyunShipment, auth: dict | None) -> None:
    """집운 기록의 국내 송장 → 국내 배송 기록. 집운 저장 뒤 부른다 (실패해도 집운 저장은 그대로)."""
    try:
        if not j.kr_tracking_no or j.deleted_at or j.status == "cancelled":
            return
        actor = actor_of(auth) if auth else SYSTEM
        order = await MarketOrder.get(id=j.order_id)
        linked = await alive().get_or_none(jiyun_id=j.id)
        if linked and linked.tracking_no != j.kr_tracking_no:
            # 집운에서 송장을 고쳤다 — 같은 기록을 고친다 (새 송장 기록이 이미 따로 있으면 그쪽에 붙인다)
            other = await alive().get_or_none(order_id=order.id, tracking_no=j.kr_tracking_no)
            if not other:
                before = _snapshot(linked)
                linked.tracking_no, linked.courier = j.kr_tracking_no, j.kr_courier or linked.courier
                linked.tracked_at, linked.track_events, linked.track_state = None, [], None
                linked.track_state_id, linked.track_location, linked.track_last_at = None, None, None
                linked.delivered_at = None
                await linked.save()
                await _log_changes(linked, before, actor)
                await _refresh_one(linked, datetime.now(timezone.utc), True, actor)
                return
        elif linked:
            if j.kr_courier and linked.courier != j.kr_courier:
                before = _snapshot(linked)
                linked.courier = j.kr_courier
                await linked.save()
                await _log_changes(linked, before, actor)
            return
        d, created = await _upsert(order, j.kr_courier, j.kr_tracking_no, "jiyun", actor, jiyun_id=j.id,
                                   user_id=(auth or {}).get("user_id"))
        if created:
            await _refresh_one(d, datetime.now(timezone.utc), True, actor)
    except Exception:
        logger.exception(f"국내 배송 기록 동기화 실패: jiyun_id={j.id}")


async def refresh_domestic(force: bool = False) -> int:
    """자동 수집 때 — 빠진 기록 만들기(집운 송장 · 마켓 송장) + 살아 있는 기록 갱신. 반환 = 바뀐 건수."""
    now = datetime.now(timezone.utc)
    # 지운 기록도 넣는다 — 사람이 지운 송장을 자동으로 되살리지 않게
    have = {(d.order_id, d.tracking_no) for d in await DomesticShipment.all().only("order_id", "tracking_no")}
    # 집운 송장 중 기록이 없는 것
    for j in await JiyunShipment.filter(deleted_at=None, kr_tracking_no__isnull=False).exclude(status="cancelled"):
        if (j.order_id, j.kr_tracking_no) not in have:
            await sync_jiyun(j, None)
            have.add((j.order_id, j.kr_tracking_no))
    # 마켓 원본에 송장이 있는데 기록이 없는 것 (사람이 마켓에서 직접 발송처리한 경우)
    since = now - timedelta(days=60)
    for o in await MarketOrder.filter(market__in=["naver", "coupang"], paid_at__gte=since).exclude(stage="cancelled"):
        m = market_delivery(o)
        if m and (o.id, m["tracking_no"]) not in have:
            await _upsert(o, courier_from_market(m["code"]), m["tracking_no"], "market", SYSTEM)
            have.add((o.id, m["tracking_no"]))
    n = 0
    for d in await alive().exclude(status="cancelled"):
        if d.status == "delivered" and d.tracked_at and not force:
            continue
        try:
            n += await _refresh_one(d, now, force, SYSTEM)
        except Exception:
            logger.exception(f"국내 배송 기록 갱신 실패: domestic_id={d.id}")
    return n


class DomesticService:
    @staticmethod
    async def list(order_id: int | None, status: str | None, q: str | None, limit: int) -> list[dict]:
        qs = alive()
        if order_id:
            qs = qs.filter(order_id=order_id)
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(tracking_no__icontains=q.replace(" ", "").replace("-", ""))
        return [await domestic_dict(d) for d in await qs.order_by("-id").limit(limit)]

    @staticmethod
    async def get(domestic_id: int) -> dict:
        d = await alive().get_or_none(id=domestic_id)
        if not d:
            raise HTTPException(status_code=404, detail="국내 배송 기록을 찾지 못했습니다.")
        return await domestic_dict(d)

    @staticmethod
    async def create(body: DomesticCreate, auth: dict) -> dict:
        order = await MarketOrder.get_or_none(id=body.order_id)
        if not order:
            raise HTTPException(status_code=404, detail="고객 주문을 찾지 못했습니다.")
        if await alive().filter(order_id=order.id, tracking_no=body.tracking_no).exists():
            raise HTTPException(status_code=409, detail=f"송장 {body.tracking_no} 는 이미 이 주문에 기록돼 있습니다.")
        actor = actor_of(auth)
        d, _ = await _upsert(order, body.courier, body.tracking_no, "manual", actor, user_id=auth.get("user_id"), memo=body.memo)
        await _refresh_one(d, datetime.now(timezone.utc), True, actor)
        return await domestic_dict(d)

    @staticmethod
    async def update(domestic_id: int, body: DomesticUpdate, auth: dict) -> dict:
        data = body.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        d = await alive().get_or_none(id=domestic_id)
        if not d:
            raise HTTPException(status_code=404, detail="국내 배송 기록을 찾지 못했습니다.")
        if data.get("tracking_no") and data["tracking_no"] != d.tracking_no:
            if await alive().filter(order_id=d.order_id, tracking_no=data["tracking_no"]).exclude(id=d.id).exists():
                raise HTTPException(status_code=409, detail=f"송장 {data['tracking_no']} 는 이미 이 주문에 기록돼 있습니다.")
            d.tracked_at, d.track_events, d.track_state, d.track_state_id = None, [], None, None
            d.track_location, d.track_last_at, d.delivered_at = None, None, None
        actor = actor_of(auth)
        before = _snapshot(d)
        retrack = "tracking_no" in data or "courier" in data
        # 상태를 problem · cancelled 에서 풀면 자동 판정으로 돌아간다
        if data.get("status") and data["status"] not in MANUAL_STATUS:
            data["status"] = "ready"
        await d.update_from_dict(data).save()
        await _log_changes(d, before, actor)
        await _refresh_one(d, datetime.now(timezone.utc), retrack, actor)
        return await domestic_dict(d)

    @staticmethod
    async def refresh(domestic_id: int, auth: dict) -> dict:
        d = await alive().get_or_none(id=domestic_id)
        if not d:
            raise HTTPException(status_code=404, detail="국내 배송 기록을 찾지 못했습니다.")
        await _refresh_one(d, datetime.now(timezone.utc), True, actor_of(auth))
        return await domestic_dict(d)

    @staticmethod
    async def delete(domestic_id: int, auth: dict) -> None:
        d = await alive().get_or_none(id=domestic_id)
        if not d:
            raise HTTPException(status_code=404, detail="국내 배송 기록을 찾지 못했습니다.")
        d.deleted_at = datetime.now(timezone.utc)
        await d.save(update_fields=["deleted_at", "updated_at"])
        order = await MarketOrder.get(id=d.order_id)
        await log_event(order, actor_of(auth), "domestic_deleted", f"국내 송장 {d.tracking_no} 기록 삭제",
                        {"domestic_id": d.id, "values": _snapshot(d)})
