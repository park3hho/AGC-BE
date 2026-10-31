"""FIN 지출 원장으로 AGC 지출 보내기 (2026-10-30 사용자 결정 — 지출 정본은 FIN 한 곳).

원본은 AGC DB 에 그대로 두고, 돈이 나간 것만 FIN /svc/expenses 에 한 줄씩 보낸다 (FIN docs/svc-expense-api.md).
- 타오바오 구매기록 → AGC-purchase-{id} (상품 매입). 취소·환불이면 AGC-purchase-{id}-refund 음수 한 줄 더
- 집운 기록 → AGC-jiyun-{id} (배송·운반)
- 마켓 판매 수수료(정산에서 떼어 감) → AGC-fee-{주문코드} (수수료, method "정산 차감"). 자사몰 결제 수수료는 SHOP-pg-fee-{주문코드}, 부서 SHOP
- 금액: 실제 청구 원화. 청구 확인 전(charged_status none)이거나 원화가 없으면 위안 × 오늘 환율로 추정 → amount_confirmed false
- 지운 기록은 FIN 에서도 지운다 (DELETE by ext_key)

보내기: 저장·삭제 직후 kick() (기다리지 않음) + 주문 자동 수집 주기마다 sync_all() — 바뀐 줄만 보낸다.
보낸 내용의 해시는 /private/fin_expense_sync.json 에 둔다. 실패한 줄은 기록하지 않아 다음 주기에 다시 보낸다 (ext_key 라 두 번 가도 한 줄).
키: .env FIN_EXPENSE_KEY (HQ API 키 fin_expense 의 agc 라벨). 키 값은 로그에 남기지 않는다."""

import asyncio
import hashlib
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
FIN_URL = os.getenv("FIN_SVC_URL", "http://fin_app:8000/svc").rstrip("/")
FIN_KEY = os.getenv("FIN_EXPENSE_KEY", "")
STATE = Path(os.getenv("PRIVATE_DIR", "/private")) / "fin_expense_sync.json"
AGC_WEB = os.getenv("AGC_WEB_URL", "https://eido-agc.vercel.app")
START = datetime(2026, 2, 27, tzinfo=KST)        # 사업 시작일
RECORDED_BY = "[AGC] 서버 자동 (fin_expense)"
_lock = asyncio.Lock()

METHOD = {"card": "현대카드", "alipay": "알리페이(현대카드)", "kakaopay": "기타", "other": "기타"}
METHOD_NOTE = {"kakaopay": "카카오페이", "other": "기타(위챗페이·위안 등)"}
MARKET_PAYEE = {"naver": "네이버 스마트스토어", "coupang": "쿠팡", "shop": "결제대행(자사몰)"}


def configured() -> bool:
    return bool(FIN_KEY)


def _day(dt) -> str | None:
    if not dt:
        return None
    if isinstance(dt, datetime):
        return dt.astimezone(KST).date().isoformat()
    return dt.isoformat()


def _num(v) -> str | None:
    return None if v is None else format(Decimal(v).normalize(), "f")


def _doc_url(d) -> str:
    return f"{AGC_WEB}/api/orders/{d.order_id}/documents/{d.id}/file"


async def _fx() -> Decimal:
    from services.pricing.exchange_rate_service import ExchangeRateService   # 늦게 import (순환 방지)
    return Decimal(str(await ExchangeRateService.current_rate()))


async def build_rows() -> tuple[dict[str, dict], set[str]]:
    """반환: ({ext_key: 보낼 줄}, 지워야 할 ext_key 집합)."""
    from models.order.document import OrderDocument
    from models.order.jiyun import JiyunShipment
    from models.order.order import MarketOrder
    from models.order.purchase import TaobaoPurchase
    from services.order.order_service import _dec, amount_of

    fx = await _fx()
    rows: dict[str, dict] = {}
    gone: set[str] = set()
    docs = {}
    for d in await OrderDocument.filter(deleted_at=None):
        docs.setdefault(("purchase", d.purchase_id), d) if d.purchase_id else None
        docs.setdefault(("jiyun", d.jiyun_id), d) if d.jiyun_id else None
    orders = {o.id: o for o in await MarketOrder.all()}

    # 타오바오 구매기록
    for p in await TaobaoPurchase.all():
        key = f"AGC-purchase-{p.id}"
        o = orders.get(p.order_id)
        when = p.purchased_at or p.created_at
        if p.deleted_at or (when and when < START):
            gone |= {key, key + "-refund"}
            continue
        cny = p.pay_amount if p.pay_currency == "CNY" and p.pay_amount else p.paid_cny
        confirmed = p.charged_krw is not None and p.charged_status in ("approved", "settled")
        if p.charged_krw is not None:
            amount = int(p.charged_krw)
        elif p.pay_currency == "KRW" and p.pay_amount:
            amount, confirmed = int(p.pay_amount), False
        else:
            amount = int((Decimal(cny or 0) * fx).quantize(Decimal("1")))
        if not amount:
            continue
        code = o.code if o else f"주문 {p.order_id}"
        memo = [f"타오바오 주문 {p.taobao_order_no}" if p.taobao_order_no else None,
                f"상품 ¥{_num(p.paid_cny)}" if p.paid_cny else None,
                METHOD_NOTE.get(p.pay_method),
                f"결제창 {p.pay_currency} {_num(p.pay_amount)}" if p.pay_amount and p.pay_currency != "CNY" else None,
                "청구 확정" if p.charged_status == "settled" else ("승인 금액" if p.charged_status == "approved" else "환율 추정")]
        doc = docs.get(("purchase", p.id))
        row = {
            "spent_on": _day(when), "amount": amount, "amount_confirmed": confirmed,
            "payee": f"타오바오 {p.shop_name}" if p.shop_name else "타오바오",
            "purpose": f"{code} 고객 주문 상품 구매 ({o.product_name[:60] if o else ''})".strip(),
            "category": "상품 매입", "method": METHOD.get(p.pay_method or "", "기타"),
            "evidence": "해외 영수증" if doc else "없음",
            "source_ref": f"AGC 구매기록 {p.id}" + (f" · 타오바오 {p.taobao_order_no}" if p.taobao_order_no else ""),
            "ext_key": key, "recorded_by": RECORDED_BY, "memo": " · ".join(x for x in memo if x),
        }
        if cny:
            row.update(currency="CNY", foreign_amount=_num(cny))
        if doc:
            row["evidence_url"] = _doc_url(doc)
        rows[key] = row
        if p.cn_status == "cancelled":
            rows[key + "-refund"] = {**row, "amount": -amount, "spent_on": _day(p.updated_at),
                                     "purpose": f"{code} 타오바오 구매 취소·환불", "ext_key": key + "-refund",
                                     "memo": "AGC 구매기록 상태 취소·환불 (환불일은 기록 수정일)"}
        else:
            gone.add(key + "-refund")

    # 집운 기록 (국제 배송비)
    for j in await JiyunShipment.all():
        key = f"AGC-jiyun-{j.id}"
        o = orders.get(j.order_id)
        when = j.requested_at or j.charged_at or j.created_at
        if j.deleted_at or j.status == "cancelled" or (when and when < START):
            gone.add(key)
            continue
        cny = j.pay_amount if j.pay_currency == "CNY" and j.pay_amount else j.fee_cny
        confirmed = j.charged_krw is not None and j.charged_status in ("approved", "settled")
        if j.charged_krw is not None:
            amount = int(j.charged_krw)
        else:
            amount = int((Decimal(cny or 0) * fx).quantize(Decimal("1")))
        if not amount:
            continue
        code = o.code if o else f"주문 {j.order_id}"
        doc = docs.get(("jiyun", j.id))
        row = {
            "spent_on": _day(when), "amount": amount, "amount_confirmed": confirmed,
            "payee": "타오바오 집운(集运)", "purpose": f"{code} 국제 배송비 (집운 {j.jiyun_no})",
            "category": "배송·운반", "method": METHOD.get(j.pay_method or "", "기타"),
            "evidence": "해외 영수증" if doc else "없음",
            "source_ref": f"AGC 집운 기록 {j.id} · {j.jiyun_no}", "ext_key": key, "recorded_by": RECORDED_BY,
            "memo": " · ".join(x for x in [METHOD_NOTE.get(j.pay_method), f"무게 {_num(j.weight_kg)}kg" if j.weight_kg else None,
                                           "청구 확정" if j.charged_status == "settled" else ("승인 금액" if j.charged_status == "approved" else "환율 추정")] if x),
        }
        if cny:
            row.update(currency="CNY", foreign_amount=_num(cny))
        if doc:
            row["evidence_url"] = _doc_url(doc)
        rows[key] = row

    # 마켓 판매 수수료 — 정산에서 떼어 감 (통장에서 따로 안 나감)
    for o in orders.values():
        shop = o.market == "shop"
        key = f"SHOP-pg-fee-{o.code}" if shop else f"AGC-fee-{o.code}"
        if not o.code or o.stage == "cancelled" or (o.paid_at and o.paid_at < START):
            gone.add(key)
            continue
        raw = json.loads(_dec(o.raw_enc) or "{}")
        a = amount_of(o, raw)
        if not a or not a.get("fee"):
            gone.add(key)
            continue
        rows[key] = {
            "spent_on": _day(o.settlement_date) or _day(o.paid_at or o.ordered_at),
            "department": "SHOP" if shop else "AGC",
            "amount": int(a["fee"]), "amount_confirmed": not a.get("estimated"),
            "payee": MARKET_PAYEE.get(o.market, o.market),
            "purpose": f"{o.code} {'결제대행' if shop else '마켓 판매'} 수수료 ({(o.product_name or '')[:50]})",
            "category": "수수료", "method": "정산 차감", "evidence": "없음",
            "source_ref": f"AGC 주문 {o.code} · {MARKET_PAYEE.get(o.market, o.market)} {o.order_no}",
            "ext_key": key, "recorded_by": RECORDED_BY,
            "memo": " · ".join(x for x in [
                ", ".join(f"{d['label']} {d['amount']:,}" for d in a.get("fee_detail") or []) or None,
                f"수수료율 {a['fee_rate']}% 추정" if a.get("estimated") and a.get("fee_rate") else None,
                "정산 실제값" if a.get("actual") else None] if x),
        }
    return rows, gone - set(rows)


# ------------------------------------------------------------ 보내기
def _call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(FIN_URL + path, method=method,
                                 data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
                                 headers={"X-Service-Key": FIN_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def _load() -> dict:
    try:
        return json.loads(STATE.read_text("utf-8"))
    except Exception:
        return {}


def _save(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=0), "utf-8")


def _hash(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


async def sync_all(force: bool = False) -> dict:
    """바뀐 줄만 FIN 에 보낸다. 반환 {sent, deleted, failed, same}."""
    if not configured():
        return {"skipped": "FIN_EXPENSE_KEY 없음"}
    async with _lock:
        rows, gone = await build_rows()
        state = {} if force else _load()
        out = {"sent": 0, "deleted": 0, "failed": 0, "same": 0, "errors": []}
        for key, row in rows.items():
            h = _hash(row)
            if state.get(key) == h:
                out["same"] += 1
                continue
            st, data = await asyncio.to_thread(_call, "POST", "/expenses", row)
            if st == 200:
                state[key] = h
                out["sent"] += 1
            else:
                out["failed"] += 1
                out["errors"].append(f"{key}: {st} {str(data.get('detail'))[:160]}")
        for key in gone:
            if key not in state and not force:
                continue
            st, _ = await asyncio.to_thread(_call, "DELETE", f"/expenses/by-key/{key}")
            if st in (200, 404):
                state.pop(key, None)
                out["deleted"] += int(st == 200)
            else:
                out["failed"] += 1
        _save(state)
        if out["failed"]:
            logger.warning(f"FIN 지출 보내기 실패 {out['failed']}건: {out['errors'][:3]}")
        return out


def kick() -> None:
    """저장·삭제 직후 — 기다리지 않고 뒤에서 보낸다 (실패하면 다음 수집 주기에 다시)."""
    if not configured():
        return
    try:
        task = asyncio.get_running_loop().create_task(sync_all())
        task.add_done_callback(lambda t: t.exception() and logger.warning(f"FIN 지출 보내기 오류: {t.exception()!r}"))
    except RuntimeError:
        pass
