"""발송기한 단계 계산 — 30분 점검 · 할 일(/ops/tasks) · 서버 자동 알림이 같은 기준을 쓴다 (2026-11-19).

기준: 마켓 발송 기한(market_order.ship_due_at)의 KST 날짜와 오늘 KST 날짜의 차이.
  d3   = 3일 · 2일 남음 (D-3, D-2 — 첫 경고)
  d1   = 1일 · 0일 남음 (D-1, 당일 — 두 번째 경고)
  over = 기한 날짜가 지남 (출고지연)
  3일보다 많이 남았거나 기한이 없으면 None.
국내 송장이 이미 마켓에 들어갔는지는 부르는 쪽이 거른다 (송장 있으면 부르지 않는다)."""
from datetime import datetime, timedelta, timezone
from typing import Optional

KST = timezone(timedelta(hours=9))
STAGES = ("d3", "d1", "over")
LABEL = {"d3": "발송기한 임박 (D-3)", "d1": "발송기한 임박 (D-1)", "over": "출고지연"}


def deadline_stage(ship_due_at: Optional[datetime], now: Optional[datetime] = None) -> Optional[dict]:
    """{stage: "d3"|"d1"|"over", days_left: int, due_on: "YYYY-MM-DD"} 또는 None (D-3 보다 여유 · 기한 없음)."""
    if ship_due_at is None:
        return None
    if ship_due_at.tzinfo is None:
        ship_due_at = ship_due_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    due = ship_due_at.astimezone(KST).date()
    left = (due - now.astimezone(KST).date()).days
    if left > 3:
        return None
    stage = "over" if left < 0 else "d1" if left <= 1 else "d3"
    return {"stage": stage, "days_left": left, "due_on": due.isoformat()}


def stage_rank(stage: Optional[str]) -> int:
    """알린 단계 비교용 — None 0 · d3 1 · d1 2 · over 3 (더 높은 단계만 새로 알린다)."""
    return STAGES.index(stage) + 1 if stage in STAGES else 0