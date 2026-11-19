"""AI·서버 알림 기록 — 같은 key 는 한 번만 알린다 (2026-11-19).

루틴은 보고하기 전에 POST /ops/alerts 를 부르고 new=true 일 때만 사용자에게 알린다.
서버 자동 처리(services/ops/auto_*)는 raise_alert() 를 직접 부른다."""

from datetime import datetime, timezone

from fastapi import HTTPException

from core.ops_config import ALERT_KIND, ALERT_LEVEL
from models.ops.alert import AgentAlert


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def alert_dict(a: AgentAlert) -> dict:
    return {
        "id": a.id, "key": a.key, "kind": a.kind, "kind_label": ALERT_KIND.get(a.kind, a.kind),
        "level": a.level, "level_label": ALERT_LEVEL.get(a.level, a.level), "title": a.title, "body": a.body,
        "order_codes": a.order_codes or [], "target": a.target, "source": a.source, "count": a.count,
        "first_at": _iso(a.first_at), "last_at": _iso(a.last_at or a.first_at),
        "resolved_at": _iso(a.resolved_at), "resolved_by": a.resolved_by,
    }


async def raise_alert(key: str, kind: str, title: str, body: str | None = None, level: str = "info",
                      order_codes: list | None = None, target: str | None = None, source: str | None = None) -> dict:
    """새 key 면 기록하고 new=True. 이미 열린 key 면 count+1 · last_at 만 갱신하고 new=False (내용은 처음 것 유지).
    resolved 된 key 면 다시 열고 new=True."""
    key = (key or "").strip()[:200]
    if not key:
        raise HTTPException(status_code=400, detail="key 가 비었어요.")
    if kind not in ALERT_KIND:
        raise HTTPException(status_code=400, detail=f"kind 는 {', '.join(ALERT_KIND)} 중 하나예요.")
    if level not in ALERT_LEVEL:
        raise HTTPException(status_code=400, detail="level 은 info · action · blocked 중 하나예요.")
    now = datetime.now(timezone.utc)
    a = await AgentAlert.get_or_none(key=key)
    if a and a.resolved_at is None:
        a.count += 1
        a.last_at = now
        await a.save(update_fields=["count", "last_at", "updated_at"])
        return {"new": False, "alert": alert_dict(a)}
    vals = dict(kind=kind, level=level, title=title[:200], body=body, order_codes=list(order_codes or []),
                target=(target or None) and str(target)[:60], source=(source or None) and str(source)[:60])
    if a:   # 해결됐던 것이 다시 생김
        await a.update_from_dict({**vals, "count": a.count + 1, "first_at": now, "last_at": now,
                                  "resolved_at": None, "resolved_by": None}).save()
    else:
        a = await AgentAlert.create(key=key, last_at=now, **vals)
    return {"new": True, "alert": alert_dict(a)}


async def list_alerts(kind: str | None, open_only: bool, since: datetime | None, q: str | None, limit: int) -> dict:
    qs = AgentAlert.all()
    if kind:
        qs = qs.filter(kind=kind)
    if open_only:
        qs = qs.filter(resolved_at=None)
    if since:
        qs = qs.filter(last_at__gte=since)
    if q:
        qs = qs.filter(key__icontains=q)
    total = await qs.count()
    rows = await qs.order_by("-last_at", "-id").limit(limit)
    return {"items": [alert_dict(a) for a in rows], "total": total}


async def resolve(alert_id: int, resolved: bool, who: str | None) -> dict:
    a = await AgentAlert.get_or_none(id=alert_id)
    if not a:
        raise HTTPException(status_code=404, detail="알림을 찾지 못했어요.")
    a.resolved_at = datetime.now(timezone.utc) if resolved else None
    a.resolved_by = (who or None) if resolved else None
    await a.save(update_fields=["resolved_at", "resolved_by", "updated_at"])
    return alert_dict(a)


async def resolve_key(key: str, who: str | None = None) -> bool:
    """서버가 상황이 끝난 걸 알면(예: 송장 등록됨) 그 key 를 닫는다."""
    n = await AgentAlert.filter(key=key, resolved_at=None).update(resolved_at=datetime.now(timezone.utc), resolved_by=who)
    return bool(n)
