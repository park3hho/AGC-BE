"""주문 접수 — 마켓 주문 수집 · 저장 · 통관부호 자동 검증 · 추적 기록.

추적 원칙: 시스템·에이전트·사람이 주문에 무언가를 하면 OrderEvent 한 줄. 무엇을 보냈고 무엇을 받았는지(개인정보는 가림)를 data 에 남긴다.
수집 1번 = OrderSyncRun 한 줄 (구간 · 건수 · 성공 여부)."""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q

from core.account_crypto import decrypt_secret, encrypt_secret
from models.order.order import MarketOrder, OrderEvent, OrderSyncRun
from services.order import market_clients as mc
from services.order.pccc import (PcccInput, check_pccc, mask_name, mask_phone, norm_pccc, norm_phone, norm_zip,
                                 receiver_fingerprint)
from utils.code_gen import CODE_ISSUE_RETRIES, ORDER_CODE_PREFIX, next_code

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
MARKETS = ("naver", "coupang")
MARKET_LABEL = {"naver": "네이버", "coupang": "쿠팡"}
FIRST_RANGE = timedelta(days=3)          # 처음 수집할 때 거슬러 올라갈 기간
OVERLAP = timedelta(minutes=10)          # 지난 수집과 겹쳐 받는 구간 (빠짐 방지)
MAX_RANGE = timedelta(days=31)
POLL_MINUTES = int(os.getenv("ORDER_POLL_MINUTES", "0") or 0)   # 0 = 자동 수집 끔 · 운영 .env 는 5분 (2026-10-25 사용자 결정)

_locks = {m: asyncio.Lock() for m in MARKETS}

NAVER_STAGE = {
    "PAYMENT_WAITING": "received", "PAYED": "received", "DELIVERING": "processing",
    "DELIVERED": "done", "PURCHASE_DECIDED": "done", "EXCHANGED": "done",
    "CANCELED": "cancelled", "RETURNED": "cancelled", "CANCELED_BY_NOPAYMENT": "cancelled",
}
COUPANG_STAGE = {
    "ACCEPT": "received", "INSTRUCT": "received", "DEPARTURE": "processing", "DELIVERING": "processing",
    "FINAL_DELIVERY": "done", "NONE_TRACKING": "processing",
}
TRACKED = ("market_status", "confirmed", "stage", "quantity", "total_price", "product_name", "option_name", "ship_due_at")


# ------------------------------------------------------------ 마켓 응답 → 한 줄
def _dt(v) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=KST)


def _money(v) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, dict):
        v = v.get("units")
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parse_naver(item: dict) -> list[dict]:
    o, po = item.get("order") or {}, item.get("productOrder") or {}
    sa = po.get("shippingAddress") or {}
    status = po.get("productOrderStatus") or ""
    return [{
        "market": "naver", "line_no": str(po["productOrderId"]), "order_no": str(o.get("orderId") or ""),
        "ship_unit_no": str(po["productOrderId"]), "market_status": status,
        "confirmed": po.get("placeOrderStatus") == "OK", "stage": NAVER_STAGE.get(status, "received"),
        "ordered_at": _dt(o.get("orderDate")), "paid_at": _dt(o.get("paymentDate")), "ship_due_at": _dt(po.get("shippingDueDate")),
        "product_name": (po.get("productName") or "")[:300], "option_name": (po.get("productOption") or None),
        "seller_code": po.get("sellerProductCode") or None,
        "market_product_id": str(po.get("originalProductId") or po.get("productId") or "") or None,
        "market_option_id": po.get("optionManageCode") or None,
        "quantity": int(po.get("quantity") or 1), "unit_price": _money(po.get("unitPrice")), "total_price": _money(po.get("totalPaymentAmount")),
        # 네이버는 통관용 전화를 따로 주지 않는다 — 배송지 tel1 을 두 칸에 같이 넣는다
        "receiver_name": sa.get("name") or "", "phone": norm_phone(sa.get("tel1")), "zip": norm_zip(sa.get("zipCode")),
        "contact_phone": norm_phone(sa.get("tel1") or sa.get("tel2")),
        "address": " ".join(x for x in (sa.get("baseAddress"), sa.get("detailedAddress")) if x),
        "pccc": norm_pccc(po.get("individualCustomUniqueCode")), "otp": None, "raw": item,
    }]


def parse_coupang(box: dict) -> list[dict]:
    rc, ov = box.get("receiver") or {}, box.get("overseaShippingInfoDto") or {}
    status = box.get("status") or ""
    pccc = norm_pccc(ov.get("personalCustomsClearanceCode") or ov.get("oneTimePccc"))
    out = []
    for oi in box.get("orderItems") or []:
        out.append({
            "market": "coupang", "line_no": f"{box['shipmentBoxId']}-{oi.get('vendorItemId')}", "order_no": str(box.get("orderId") or ""),
            "ship_unit_no": str(box["shipmentBoxId"]), "market_status": status,
            "confirmed": status not in ("ACCEPT", ""),
            "stage": "cancelled" if oi.get("canceled") else COUPANG_STAGE.get(status, "received"),
            "ordered_at": _dt(box.get("orderedAt")), "paid_at": _dt(box.get("paidAt")), "ship_due_at": _dt(oi.get("estimatedShippingDate")),
            "product_name": (oi.get("sellerProductName") or oi.get("vendorItemName") or "")[:300],
            "option_name": oi.get("sellerProductItemName") or oi.get("vendorItemName") or None,
            "seller_code": oi.get("externalVendorSkuCode") or None,
            "market_product_id": str(oi.get("sellerProductId") or "") or None, "market_option_id": str(oi.get("vendorItemId") or "") or None,
            "quantity": int(oi.get("shippingCount") or 1), "unit_price": _money(oi.get("salesPrice")), "total_price": _money(oi.get("orderPrice")),
            # phone = 통관용 (구매자가 통관 정보로 넣은 번호) · contact_phone = 쿠팡 연락처 (실번호 없으면 안심번호)
            "receiver_name": rc.get("name") or "", "phone": norm_phone(ov.get("ordererPhoneNumber")), "zip": norm_zip(rc.get("postCode")),
            "contact_phone": norm_phone(rc.get("receiverNumber") or rc.get("safeNumber")),
            "address": " ".join(x for x in (rc.get("addr1"), rc.get("addr2")) if x),
            "pccc": pccc, "otp": ov.get("otpNumber") or None, "raw": box,
        })
    return out


# ------------------------------------------------------------ 기록
def _enc(v: str | None) -> str | None:
    return encrypt_secret(v) if v else None


def _dec(v: str | None) -> str:
    return decrypt_secret(v) if v else ""


def actor_of(auth: dict | None, trigger: str = "manual") -> dict:
    """기록에 남길 '누가'. 폴링 = system, API 키 = agent, 로그인 사용자 = user."""
    if not auth:
        return {"actor_type": "system", "actor_user_id": None, "via": "poller" if trigger == "poller" else "system"}
    if auth.get("via_api_key"):
        return {"actor_type": "agent", "actor_user_id": auth["user_id"], "via": "api_key"}
    return {"actor_type": "user", "actor_user_id": auth["user_id"], "via": "session"}


async def log_event(order, actor: dict, kind: str, summary: str, data: dict | None = None, run=None) -> OrderEvent:
    return await OrderEvent.create(
        order=order, sync_run=run, actor_type=actor["actor_type"], actor_user_id=actor["actor_user_id"], via=actor["via"],
        kind=kind, summary=summary[:300], data=json.loads(json.dumps(data or {}, default=str, ensure_ascii=False)),
    )


# 마켓 원본 응답을 보여줄 때 가릴 키 (개인정보) — 상품명 같은 *Name 은 그대로 둔다
PERSONAL_KEYS = {
    "name", "ordererName", "ordererId", "ordererNo", "ordererTel", "tel1", "tel2", "safeNumber", "receiverNumber",
    "ordererNumber", "ordererPhoneNumber", "email", "baseAddress", "detailedAddress", "addr1", "addr2",
    "consigneePrimaryAddress", "individualCustomUniqueCode", "personalCustomsClearanceCode", "oneTimePccc",
    "otpNumber", "orderersSsn", "ordererSsn", "pickupLocationContent", "entryMethodContent", "shippingMemo",
    "parcelPrintMessage",
}


def mask_raw(v, key: str | None = None):
    """원본 응답의 구조·필드는 그대로 두고 개인정보 값만 가린다."""
    if isinstance(v, dict):
        return {k: mask_raw(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [mask_raw(x, key) for x in v]
    if key in PERSONAL_KEYS and isinstance(v, str) and v:
        return v[0] + "*" * min(8, max(1, len(v) - 1)) if len(v) > 1 else "*"
    return v


def _fmt(v):
    return v.isoformat() if isinstance(v, datetime) else v


# ------------------------------------------------------------ 통관부호 검증
def _pccc_input(o: MarketOrder) -> PcccInput:
    raw = json.loads(_dec(o.raw_enc) or "{}")
    otp = (raw.get("overseaShippingInfoDto") or {}).get("otpNumber") if o.market == "coupang" else None
    return PcccInput(
        pccc=_dec(o.pccc_enc), name=o.receiver_name or "", phone=_dec(o.receiver_phone_enc), zip_code=o.receiver_zip or "",
        order_no=o.order_no or None, ordered_at=o.ordered_at.astimezone(KST).strftime("%Y%m%d%H%M%S") if o.ordered_at else None,
        otp=otp,
    )


async def run_pccc_check(o: MarketOrder, actor: dict, reason: str, run=None) -> MarketOrder:
    inp = _pccc_input(o)
    res = await check_pccc(inp)
    o.pccc_status, o.pccc_message = res.status, res.message[:1000]
    o.pccc_checked_at = datetime.now(timezone.utc)
    o.pccc_valid_to = res.valid_to
    await o.save(update_fields=["pccc_status", "pccc_message", "pccc_checked_at", "pccc_valid_to", "updated_at"])
    label = {"ok": "일치", "mismatch": "불일치", "missing": "검증 못 함", "error": "오류"}[res.status]
    await log_event(o, actor, "pccc_check", f"통관부호 검증 {label} — {res.message}"[:300], {
        "reason": reason, "called_unipass": res.called, "api": "UNI-PASS API028",
        "sent": inp.masked() if res.called else None, "input": inp.masked(),
        "result": {"status": res.status, "tCnt": res.t_cnt, "message": res.message, "reasons": res.reasons,
                   "valid_to": res.valid_to, "email_verified": res.email_verified},
    }, run)
    if run is not None and res.called:
        run.checked += 1
    return o


# ------------------------------------------------------------ 자사 주문 코드 OR-YYMMDD-XXXX
async def issue_code(o: MarketOrder, actor: dict, run=None) -> str:
    """코드가 없으면 발급 (날짜 = 마켓 주문일 KST, 없으면 결제일·오늘). 동시에 같은 번호를 잡으면 다시 발급."""
    if o.code:
        return o.code
    base = o.ordered_at or o.paid_at or datetime.now(timezone.utc)
    day = base.astimezone(KST).date()
    for _ in range(CODE_ISSUE_RETRIES):
        o.code = await next_code(MarketOrder, ORDER_CODE_PREFIX, day)
        try:
            await o.save(update_fields=["code", "updated_at"])
        except IntegrityError:
            o.code = None
            continue
        await log_event(o, actor, "code_issued", f"자사 주문 코드 {o.code} 발급",
                        {"code": {"from": None, "to": o.code}, "order_no": o.order_no, "line_no": o.line_no}, run)
        return o.code
    raise HTTPException(status_code=409, detail="자사 주문 코드를 발급하지 못했습니다. 잠시 후 다시 시도해주세요.")


# ------------------------------------------------------------ 저장 (새 주문 · 바뀐 주문)
async def upsert_line(line: dict, actor: dict, run) -> str:
    """반환: created · changed · same."""
    fp = receiver_fingerprint(line["pccc"], line["receiver_name"], line["phone"], line["zip"])
    fields = {k: line[k] for k in ("order_no", "ship_unit_no", "market_status", "confirmed", "stage", "ordered_at", "paid_at",
                                   "ship_due_at", "product_name", "option_name", "seller_code", "market_product_id",
                                   "market_option_id", "quantity", "unit_price", "total_price", "receiver_name")}
    fields.update(receiver_zip=line["zip"] or None, receiver_hash=fp, last_synced_at=datetime.now(timezone.utc),
                  raw_enc=_enc(json.dumps(line["raw"], ensure_ascii=False, default=str)))
    secret = {"receiver_phone_enc": _enc(line["phone"]), "contact_phone_enc": _enc(line.get("contact_phone")),
              "receiver_address_enc": _enc(line["address"]), "pccc_enc": _enc(line["pccc"])}
    m = MARKET_LABEL[line["market"]]
    o = await MarketOrder.get_or_none(market=line["market"], line_no=line["line_no"])

    if o is None:
        o = await MarketOrder.create(market=line["market"], line_no=line["line_no"], **fields, **secret)
        await issue_code(o, actor, run)
        await log_event(o, actor, "collected", f"{m} 주문 수집 — {line['product_name'][:60]} ×{line['quantity']} ({line['market_status']})", {
            "code": o.code, "market": line["market"], "line_no": line["line_no"], "order_no": line["order_no"], "market_status": line["market_status"],
            "confirmed": line["confirmed"], "quantity": line["quantity"], "total_price": line["total_price"],
            "receiver": {"name": mask_name(line["receiver_name"]), "phone": mask_phone(line["phone"]), "zip": line["zip"]},
        }, run)
        if o.stage != "cancelled":
            await run_pccc_check(o, actor, "새 주문", run)
        return "created"

    diff = {k: [_fmt(getattr(o, k)), _fmt(fields[k])] for k in TRACKED if getattr(o, k) != fields[k]}
    receiver_changed = o.receiver_hash != fp
    for k, v in {**fields, **secret}.items():
        setattr(o, k, v)
    await o.save()
    if not diff and not receiver_changed:
        return "same"
    data = {"diff": diff}
    if receiver_changed:
        data["receiver_now"] = {"name": mask_name(line["receiver_name"]), "phone": mask_phone(line["phone"]), "zip": line["zip"]}
    names = {"market_status": "상태", "confirmed": "발주확인", "stage": "단계", "quantity": "수량", "total_price": "금액"}
    parts = [f"{names[k]} {a}→{b}" for k, (a, b) in diff.items() if k in names]
    if receiver_changed:
        parts.append("수취인·통관 정보 바뀜")
    await log_event(o, actor, "changed", f"{m} 주문 변경 — " + ", ".join(parts or ["세부 정보"]), data, run)
    # 마켓에서 발주확인이 된 걸 수집으로 알게 됨 (AGC 발주확인 버튼으로 보낸 게 아님) — 단계가 보이게 따로 남긴다
    if diff.get("confirmed", [None, None])[1] is True:
        await log_event(o, actor, "market_confirmed", f"{m} 발주확인됨 — 마켓에서 확인 (수집으로 감지, AGC 에서 보낸 것 아님)", {
            "step": "발주확인", "stage": "receive", "source": f"{line['market']}_api", "detected_by": "collect",
            "status": {"from": diff.get("market_status", [o.market_status, o.market_status])[0], "to": line["market_status"]},
        }, run)
    if receiver_changed and o.stage != "cancelled":
        await run_pccc_check(o, actor, "수취인·통관 정보 바뀜", run)
    return "changed"


# ------------------------------------------------------------ 한 주문만 다시 보기 · 발주확인 시각
async def refresh_order(o: MarketOrder, actor: dict, reason: str) -> MarketOrder:
    """이 주문 하나만 마켓에서 바로 다시 받아 저장한다 (바뀐 게 있으면 changed · market_confirmed 기록).
    마켓에서 바로 한 발주확인을 AGC 가 아직 모를 때 — 예: 타오바오 구매 등록 직전."""
    if o.market == "coupang":
        box = await mc.coupang_ordersheet(o.ship_unit_no)
        lines = parse_coupang(box) if box else []
    else:
        items = await mc.naver_product_orders([o.ship_unit_no])
        lines = [ln for it in items for ln in parse_naver(it)]
    for ln in lines:
        if ln["line_no"] == o.line_no:
            await upsert_line(ln, actor, None)
    fresh = await MarketOrder.get(id=o.id)
    logger.info(f"주문 다시 보기: order_id={o.id} reason={reason} confirmed={fresh.confirmed}")
    return fresh


async def confirmed_at(o: MarketOrder) -> datetime | None:
    """발주확인된 시각 — AGC 가 보낸 기록(market_confirmed)이나 수집으로 알게 된 기록 중 가장 이른 것.
    수집으로 알게 된 경우는 '알게 된 시각'이라 실제보다 늦을 수 있다."""
    times = []
    for e in await OrderEvent.filter(order_id=o.id, kind__in=["market_confirmed", "changed"]).order_by("id"):
        d = e.data or {}
        if e.kind == "changed" and (d.get("diff") or {}).get("confirmed", [None, None])[1] is not True:
            continue
        times.append(_dt(d.get("occurred_at")) or e.created_at)
    return min(times) if times else None


# ------------------------------------------------------------ 수집
async def _default_range(market: str, now: datetime) -> tuple[datetime, datetime]:
    last = await OrderSyncRun.filter(market=market, ok=True).order_by("-range_to").first()
    start = (last.range_to - OVERLAP) if last else now - FIRST_RANGE
    return max(start, now - MAX_RANGE), now


async def collect_market(market: str, auth: dict | None, trigger: str = "manual", since: datetime | None = None) -> OrderSyncRun:
    if market not in MARKETS:
        raise HTTPException(status_code=400, detail="알 수 없는 마켓입니다.")
    lock = _locks[market]
    if lock.locked():
        raise HTTPException(status_code=409, detail=f"{MARKET_LABEL[market]} 주문을 이미 가져오는 중입니다.")
    async with lock:
        now = datetime.now(timezone.utc)
        start, end = await _default_range(market, now)
        if since is not None:
            start = max(since, now - MAX_RANGE)
        actor = actor_of(auth, trigger)
        run = await OrderSyncRun.create(market=market, trigger=trigger, actor_user_id=actor["actor_user_id"], range_from=start, range_to=end)
        try:
            if market == "naver":
                ids = await mc.naver_changed_product_order_ids(start, end)
                items = await mc.naver_product_orders(ids) if ids else []
                lines = [ln for it in items for ln in parse_naver(it)]
            else:
                boxes = await mc.coupang_ordersheets(start, end)
                lines = [ln for b in boxes for ln in parse_coupang(b)]
            run.fetched = len(lines)
            for ln in lines:
                r = await upsert_line(ln, actor, run)
                if r == "created":
                    run.created += 1
                elif r == "changed":
                    run.changed += 1
            run.ok = True
        except (mc.MarketApiError, HTTPException) as e:
            run.ok, run.error = False, (e.detail if isinstance(e, HTTPException) else str(e))[:1000]
            logger.warning(f"주문 수집 실패: market={market} run={run.id} {run.error}")
        except Exception as e:
            run.ok, run.error = False, f"처리 중 오류 ({type(e).__name__})"
            logger.exception(f"주문 수집 오류: market={market} run={run.id}")
        run.finished_at = datetime.now(timezone.utc)
        await run.save()
        return run


async def order_poll_loop() -> None:
    """ORDER_POLL_MINUTES 마다 두 마켓 주문을 가져온다. 0 이면 돌지 않는다 (운영은 5분 — 2026-10-25)."""
    if POLL_MINUTES <= 0:
        return
    while True:
        await asyncio.sleep(POLL_MINUTES * 60)
        for m in MARKETS:
            try:
                await collect_market(m, None, "poller")
            except HTTPException:
                pass       # 이미 수집 중
            except Exception:
                logger.exception(f"주문 자동 수집 실패: {m}")


# ------------------------------------------------------------ 조회
def run_dict(r: OrderSyncRun | None) -> dict | None:
    if not r:
        return None
    return {"id": r.id, "market": r.market, "trigger": r.trigger, "actor_user_id": r.actor_user_id,
            "range_from": r.range_from.isoformat(), "range_to": r.range_to.isoformat(),
            "started_at": r.created_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "fetched": r.fetched, "created": r.created, "changed": r.changed, "checked": r.checked, "ok": r.ok, "error": r.error}


def _short_address(addr: str) -> str:
    parts = addr.split()
    return " ".join(parts[:2]) + (" …" if len(parts) > 2 else "")


def order_dict(o: MarketOrder) -> dict:
    phone, pccc, contact = _dec(o.receiver_phone_enc), _dec(o.pccc_enc), _dec(o.contact_phone_enc)
    from services.order.pccc import mask_pccc
    return {
        "id": o.id, "code": o.code, "market": o.market, "line_no": o.line_no, "order_no": o.order_no, "ship_unit_no": o.ship_unit_no,
        "market_status": o.market_status, "confirmed": o.confirmed, "stage": o.stage,
        "ordered_at": _fmt(o.ordered_at), "paid_at": _fmt(o.paid_at), "ship_due_at": _fmt(o.ship_due_at),
        "product_name": o.product_name, "option_name": o.option_name, "seller_code": o.seller_code,
        "market_product_id": o.market_product_id, "market_option_id": o.market_option_id,
        "quantity": o.quantity, "unit_price": o.unit_price, "total_price": o.total_price,
        "receiver": {"name": mask_name(o.receiver_name or ""), "phone": mask_phone(phone) if phone else None,
                     "contact_phone": mask_phone(contact) if contact else None,
                     "zip": o.receiver_zip, "address": _short_address(_dec(o.receiver_address_enc)) or None,
                     "pccc": mask_pccc(pccc) if pccc else None},
        "pccc_status": o.pccc_status, "pccc_message": o.pccc_message,
        "pccc_checked_at": _fmt(o.pccc_checked_at), "pccc_valid_to": o.pccc_valid_to.isoformat() if o.pccc_valid_to else None,
        "last_synced_at": _fmt(o.last_synced_at), "created_at": o.created_at.isoformat(),
    }


def receiver_full(o: MarketOrder) -> dict:
    """주문 상세 전용 — 타오바오 주문·배송에 쓸 수취인 원본. 목록에는 넣지 않는다.
    customs_phone(통관용) · contact_phone(쇼핑몰 연락처) 은 덮어쓰지 않고 따로 준다."""
    return {
        "name": o.receiver_name or "", "zip": o.receiver_zip or "", "address": _dec(o.receiver_address_enc),
        "customs_phone": _dec(o.receiver_phone_enc), "contact_phone": _dec(o.contact_phone_enc), "pccc": _dec(o.pccc_enc),
    }


def event_dict(e: OrderEvent) -> dict:
    return {"id": e.id, "at": e.created_at.isoformat(), "actor_type": e.actor_type, "actor_user_id": e.actor_user_id,
            "actor_name": getattr(e.actor_user, "name", None) if e.actor_user_id else None,
            "via": e.via, "kind": e.kind, "summary": e.summary, "data": e.data, "sync_run_id": e.sync_run_id}


class OrderService:
    @staticmethod
    async def list(stage: str | None, market: str | None, pccc: str | None, page: int, size: int, q: str | None = None) -> dict:
        qs = MarketOrder.all()
        if q:   # 자사 코드 · 마켓 주문번호 · 줄 번호
            q = q.strip()
            qs = qs.filter(Q(code__icontains=q) | Q(order_no__icontains=q) | Q(line_no__icontains=q))
        if stage:
            qs = qs.filter(stage=stage)
        if market:
            qs = qs.filter(market=market)
        base = qs
        if pccc:
            qs = qs.filter(pccc_status=pccc)
        total = await qs.count()
        rows = await qs.order_by("-ordered_at", "-id").offset((page - 1) * size).limit(size)
        counts = {s: await base.filter(pccc_status=s).count() for s in ("ok", "mismatch", "missing", "error", "pending")}
        runs = {m: run_dict(await OrderSyncRun.filter(market=m).order_by("-id").first()) for m in MARKETS}
        return {"items": [order_dict(o) for o in rows], "total": total, "page": page, "size": size,
                "pccc_counts": counts, "last_runs": runs, "poll_minutes": POLL_MINUTES}

    @staticmethod
    async def get(order_id: int) -> dict:
        o = await MarketOrder.get_or_none(id=order_id)
        if not o:
            raise HTTPException(status_code=404, detail="주문을 찾지 못했습니다.")
        events = await OrderEvent.filter(order_id=o.id).order_by("-id").prefetch_related("actor_user")
        raw = json.loads(_dec(o.raw_enc) or "null")
        return {"order": order_dict(o), "events": [event_dict(e) for e in events], "raw_masked": mask_raw(raw),
                "receiver_full": receiver_full(o)}

    @staticmethod
    async def recheck(order_id: int, auth: dict) -> dict:
        o = await MarketOrder.get_or_none(id=order_id)
        if not o:
            raise HTTPException(status_code=404, detail="주문을 찾지 못했습니다.")
        await run_pccc_check(o, actor_of(auth), "다시 검증 (사람)")
        return await OrderService.get(order_id)

    @staticmethod
    async def collect_status() -> dict:
        runs = {m: run_dict(await OrderSyncRun.filter(market=m).order_by("-id").first()) for m in MARKETS}
        return {"last_runs": runs, "poll_minutes": POLL_MINUTES}

    @staticmethod
    async def runs(market: str | None, limit: int) -> list[dict]:
        qs = OrderSyncRun.all()
        if market:
            qs = qs.filter(market=market)
        return [run_dict(r) for r in await qs.order_by("-id").limit(limit)]

    @staticmethod
    async def confirm(order_id: int, auth: dict) -> dict:
        """발주확인 — 마켓에 '주문 확인했어요'를 보낸다 (쿠팡 ACCEPT → 상품준비중 · 네이버 발주 확인).
        고객 화면이 결제완료 → 상품준비중으로 바뀌어 즉시 취소가 막힌다 (취소는 요청 → 판매자 승인).
        같은 처리 단위(쿠팡 묶음배송 · 네이버 상품주문)의 AGC 주문 줄은 함께 확인 처리한다.
        실패하면 409 + 마켓이 준 이유. 성공·실패 모두 OrderEvent(kind=market_confirmed / market_confirm_failed)."""
        o = await MarketOrder.get_or_none(id=order_id)
        if not o:
            raise HTTPException(status_code=404, detail="주문을 찾지 못했습니다.")
        actor = actor_of(auth)
        if o.confirmed:
            return {**await OrderService.get(order_id), "already": True}
        if o.stage == "cancelled":
            raise HTTPException(status_code=409, detail="취소된 주문이라 발주확인을 보낼 수 없습니다.")
        label = MARKET_LABEL.get(o.market, o.market)
        sent = {"market": o.market, "ship_unit_no": o.ship_unit_no, "market_status_before": o.market_status}
        try:
            if o.market == "coupang":
                if o.market_status != "ACCEPT":
                    raise HTTPException(status_code=409, detail=f"쿠팡 상태가 결제완료(ACCEPT)가 아니라서 보낼 수 없습니다 (지금 {o.market_status}). 먼저 다시 수집해 주세요.")
                res = await mc.coupang_acknowledge([o.ship_unit_no])
            else:
                res = await mc.naver_confirm([o.ship_unit_no])
        except mc.MarketApiError as e:
            await log_event(o, actor, "market_confirm_failed", f"{label} 발주확인 실패 — {str(e)[:120]}", {"sent": sent, "error": str(e)})
            raise HTTPException(status_code=409, detail=f"{label} 발주확인 실패: {str(e)[:200]}") from None
        ok, msg = res["result"].get(str(o.ship_unit_no), (False, "마켓 응답에 이 주문이 없음"))
        received = {"ok": ok, "message": msg}
        if not ok:
            await log_event(o, actor, "market_confirm_failed", f"{label} 발주확인 실패 — {msg[:120]}", {"sent": sent, "received": received})
            raise HTTPException(status_code=409, detail=f"{label} 발주확인 실패: {msg or '이유 없음'}")

        rows = await MarketOrder.filter(market=o.market, ship_unit_no=o.ship_unit_no)
        for r in rows:
            before = {"confirmed": r.confirmed, "market_status": r.market_status}
            r.confirmed = True
            if r.market == "coupang":
                r.market_status = "INSTRUCT"
            await r.save(update_fields=["confirmed", "market_status", "updated_at"])
            await log_event(r, actor, "market_confirmed", f"{label} 발주확인 보냄 — 고객 화면 상품준비중", {
                "sent": sent, "received": received,
                "changes": {"confirmed": {"from": before["confirmed"], "to": True},
                            "market_status": {"from": before["market_status"], "to": r.market_status}},
            })
        return await OrderService.get(order_id)
