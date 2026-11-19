"""카드 결제 자동 대조 — 타오바오 구매 · 집운 배송비의 카드 결제를 FIN 카드 승인 내역과 맞춘다 (2026-11-19).

30분 점검이 매 회차 손으로 하던 일(ops-check.md '카드 결제(VISA 8904)')을 서버가 한다.
대상: charged_status "none" + pay_method card · alipay(현대카드 연동) + 지운 것 아님 + 최근 45일.
  (알리페이 잔액 결제는 저장할 때 이미 settled — 대상 아님)
후보: FIN GET /svc/card-transactions?q=taobao (가맹점 ALP*Taobao, 취소 제외, 대조 기준 줄)
맞춤: 결제 시각 ±15분 + 금액이 예상 원화의 ±5% — 여럿이면 시각이 가장 가까운 것. 한 승인은 한 기록에만.
  예상 원화 = 저장된 추정 charged_krw → 결제창 원화(pay_currency KRW) → 위안 × 204.4 순.
맞으면: charged_krw = 승인 금액, charged_status "approved", charged_at = 승인 시각,
        charged_source "현대카드 승인 {금액}원 ({가맹점} {MM-DD HH:MM}, FIN 카드 #{id} 자동 대조)"
        → FIN 지출 다시 보내기(kick) → AI 알림 card_confirmed:{purchase|jiyun}:{id} (info).
이미 approved · settled 는 건드리지 않는다. 못 찾으면 다음 주기에 다시 (알리지 않음)."""

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
FIN_URL = os.getenv("FIN_SVC_URL", "http://fin_app:8000/svc").rstrip("/")
FIN_KEY = os.getenv("FIN_EXPENSE_KEY", "")
WINDOW = timedelta(minutes=15)
AMOUNT_TOL = 0.05
LOOKBACK_DAYS = 45
CARD_RATE = Decimal("204.4")      # 카드 결제 추정 환율 (ops-check.md 와 같음)
MERCHANT_Q = "taobao"
USED_RE = re.compile(r"FIN 카드 #(\d+)")


def _fetch_card(start: str) -> list[dict]:
    url = f"{FIN_URL}/card-transactions?" + urllib.parse.urlencode({"q": MERCHANT_Q, "start": start, "size": 200})
    req = urllib.request.Request(url, headers={"X-Service-Key": FIN_KEY})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read()).get("items", [])


def _card_dt(it: dict) -> Optional[datetime]:
    t = (it.get("used_time") or "").ljust(6, "0")[:6]
    if not t.isdigit():
        return None
    d = datetime.fromisoformat(it["used_date"])
    return d.replace(hour=int(t[:2]), minute=int(t[2:4]), second=int(t[4:6]), tzinfo=KST)


def _expected(x, cny) -> Optional[int]:
    if x.charged_krw:
        return int(x.charged_krw)
    if (x.pay_currency or "").upper() == "KRW" and x.pay_amount:
        return int(x.pay_amount)
    if cny:
        return int((Decimal(cny) * CARD_RATE).quantize(Decimal("1")))
    return None


async def run_once() -> dict:
    """한 번 대조. 반환: {checked, matched:[{kind,id,amount}], skipped}"""
    from models.order.jiyun import JiyunShipment
    from models.order.order import MarketOrder
    from models.order.purchase import TaobaoPurchase

    out = {"checked": 0, "matched": [], "candidates": 0}
    if not FIN_KEY:
        return out
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    targets = []
    for x in await TaobaoPurchase.filter(deleted_at=None, charged_status="none", pay_method__in=["card", "alipay"],
                                         purchased_at__gte=since):
        targets.append(("purchase", x, x.purchased_at, x.paid_cny))
    for x in await JiyunShipment.filter(deleted_at=None, charged_status="none", pay_method__in=["card", "alipay"],
                                        requested_at__gte=since):
        targets.append(("jiyun", x, x.requested_at, x.fee_cny))
    out["checked"] = len(targets)
    if not targets:
        return out

    start = (min(t[2] for t in targets if t[2]) - timedelta(days=1)).astimezone(KST).date().isoformat()
    import asyncio
    cards = await asyncio.to_thread(_fetch_card, start)
    out["candidates"] = len(cards)
    # 이미 다른 기록에 쓴 승인
    used: set[int] = set()
    for M in (TaobaoPurchase, JiyunShipment):
        for s in await M.filter(charged_source__contains="FIN 카드 #").values_list("charged_source", flat=True):
            used.update(int(m) for m in USED_RE.findall(s or ""))
    pool = [(c, _card_dt(c)) for c in cards if c.get("amount") and c["amount"] > 0 and c["id"] not in used]

    for kind, x, at, cny in sorted(targets, key=lambda t: t[2]):
        exp = _expected(x, cny)
        if not at or not exp:
            continue
        best = None
        for c, cdt in pool:
            if not cdt or abs(cdt - at) > WINDOW:
                continue
            if abs(c["amount"] - exp) > exp * AMOUNT_TOL:
                continue
            gap = abs(cdt - at)
            if best is None or gap < best[2]:
                best = (c, cdt, gap)
        if not best:
            continue
        c, cdt, _ = best
        pool = [p for p in pool if p[0]["id"] != c["id"]]
        src = f"현대카드 승인 {c['amount']:,}원 ({c['merchant'][:20]} {cdt.strftime('%m-%d %H:%M')}, FIN 카드 #{c['id']} 자동 대조)"[:100]
        M = TaobaoPurchase if kind == "purchase" else JiyunShipment
        n = await M.filter(id=x.id, charged_status="none").update(
            charged_krw=int(c["amount"]), charged_status="approved", charged_at=cdt, charged_source=src)
        if not n:
            continue
        out["matched"].append({"kind": kind, "id": x.id, "amount": c["amount"], "expected": exp})
        logger.info(f"카드 자동 대조: {kind} {x.id} → FIN 카드 #{c['id']} {c['amount']}원 (예상 {exp})")
        try:
            o = await MarketOrder.get_or_none(id=x.order_id)
            code = o.code if o else None
            from services.ops.alerts import raise_alert
            await raise_alert(key=f"card_confirmed:{kind}:{x.id}", kind="card_confirmed", level="info",
                              title=f"카드값 확정 {c['amount']:,}원 ({'구매' if kind == 'purchase' else '집운'} {x.id})",
                              body=f"예상 {exp:,}원 → 승인 {c['amount']:,}원, {src}",
                              order_codes=[code] if code else [], target=f"{kind}:{x.id}", source="auto:card")
        except ImportError:
            pass        # 알림 기록(services/ops/alerts.py)이 아직 없을 때
        except Exception:
            logger.exception("카드 대조 알림 기록 실패")
    if out["matched"]:
        try:
            from services.finance import fin_expense
            fin_expense.kick()
        except Exception:
            logger.exception("FIN 지출 다시 보내기 실패")
    return out
