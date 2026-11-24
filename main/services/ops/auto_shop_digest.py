"""자사몰 유입 하루 요약 — AI 루틴(6시간마다) 대신 서버가 하루 한 번 (2026-11-23 사용자: '하루에 한 번만, 루틴 끄고 싶다').

매일 SHOP_DIGEST_HOUR(기본 9)시 KST 가 지나면 그날 한 번: 지난 24시간 유입 요약(shop_analytics.digest)을
AI 알림(kind shop_digest, key shop_digest:YYYY-MM-DD)으로 남긴다 → AGC 판매 › 오늘 할 일 › AI 알림 에서 본다.
진짜 손님 · 바깥 유입 · 결제가 있으면 level action(눈에 띄게), 없으면 info. 오늘 것이 이미 있으면 건너뛴다(서버 재시작해도 한 번)."""
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
HOUR = int(os.getenv("SHOP_DIGEST_HOUR", "9") or 9)


async def run_once(force: bool = False) -> dict:
    now = datetime.now(KST)
    if not force and now.hour < HOUR:
        return {"skipped": "before_hour"}
    key = f"shop_digest:{now.date().isoformat()}"
    from models.ops.alert import AgentAlert
    from services.ops.alerts import raise_alert
    if not force and await AgentAlert.filter(key=key).exists():
        return {"skipped": "done_today"}
    from scripts.shop_digest import text
    from services import shop_analytics

    d = await shop_analytics.digest(24)
    r = d["real"]
    title = (f"자사몰 어제~오늘 진짜 손님 {r['visitors']}명 · 상품 조회 {r['product_views']} · 주문 {r['orders']}건"
             + (f" {r['revenue']:,}원" if r["revenue"] else ""))
    body = "\n".join(text(d).split("\n")[1:])
    res = await raise_alert(key=key, kind="shop_digest", level="action" if d["notable"] else "info", title=title,
                            body=body[:2000], source="auto:shop_digest")
    return {"new": res.get("new"), "notable": d["notable"], "visitors": r["visitors"]}