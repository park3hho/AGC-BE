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
from models.order.jiyun import JiyunShipment
from models.order.purchase import TaobaoPurchase
from services.order import market_clients as mc
from services.order import shop_orders as so
from services.order.pccc import (PcccInput, check_pccc, mask_name, mask_phone, norm_pccc, norm_phone, norm_zip,
                                 receiver_fingerprint)
from utils.code_gen import CODE_ISSUE_RETRIES, ORDER_CODE_PREFIX, next_code

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
MARKETS = ("naver", "coupang", "shop")
MARKET_LABEL = {"naver": "네이버", "coupang": "쿠팡", "shop": "자사몰"}
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
TRACKED = ("market_status", "confirmed", "stage", "quantity", "total_price", "product_name", "option_name", "ship_due_at",
           "claim_type", "claim_status")
CLAIM_FIELDS = ("claim_type", "claim_status", "claim_at")
CLAIM_LABEL = {"CANCEL": "취소", "ADMIN_CANCEL": "취소(관리자)", "RETURN": "반품", "EXCHANGE": "교환",
               "STOP_SHIPPING": "출고중지 요청", "PURCHASE_DECISION_HOLDBACK": "구매확정 보류"}


def run_tag(run) -> dict:
    """이벤트에 남길 수집 실행 정보 — 자동(poller)·수동 중 무엇으로 들어왔는지."""
    if not run:
        return {}
    return {"run": {"id": run.id, "trigger": run.trigger, "auto": run.trigger == "poller"}}


def run_suffix(run) -> str:
    if not run:
        return ""
    return " · 자동 수집" if run.trigger == "poller" else " · 수동 수집"


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


def _naver_claim_at(item: dict, claim_type: str | None) -> datetime | None:
    """네이버 클레임 접수 시각 — item 의 cancel · return · exchange 묶음 중 클레임 종류에 맞는 것."""
    if not claim_type:
        return None
    key = {"CANCEL": "cancel", "ADMIN_CANCEL": "cancel", "RETURN": "return", "EXCHANGE": "exchange"}.get(claim_type)
    c = (item.get(key) or {}) if key else {}
    return _dt(c.get("claimRequestDate") or c.get("requestDate"))


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
        # 클레임 — 없으면 빈 문자열이 온다 → None
        "claim_type": po.get("claimType") or None, "claim_status": po.get("claimStatus") or None,
        "claim_at": _naver_claim_at(item, po.get("claimType")),
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
# ------------------------------------------------------------ 단계 판정 (2026-10-27)
STAGE_LABEL = {"received": "접수", "processing": "처리", "done": "완료", "cancelled": "취소"}
PROGRESS_STEPS = ("타오바오 구매", "판매처 발송", "집운 입고", "국제 발송")


def market_stage(o_or_line) -> str:
    status = o_or_line["market_status"] if isinstance(o_or_line, dict) else o_or_line.market_status
    market = o_or_line["market"] if isinstance(o_or_line, dict) else o_or_line.market
    if market == "shop":
        return so.SHOP_STAGE.get(status, "received")
    return (NAVER_STAGE if market == "naver" else COUPANG_STAGE).get(status, "received")


def decide_stage(mstage: str, claim_cancelled: bool, purchased: bool) -> str:
    """취소·반품 > 배송완료(완료) > 배송중 또는 타오바오 구매 기록 있음(처리) > 그 외(접수)."""
    if claim_cancelled or mstage == "cancelled":
        return "cancelled"
    if mstage == "done":
        return "done"
    if mstage == "processing" or purchased:
        return "processing"
    return "received"


async def has_purchase(order_id: int) -> bool:
    """살아 있는 타오바오 구매 기록 (취소·환불 상태는 뺀다)."""
    return await TaobaoPurchase.filter(order_id=order_id, deleted_at=None).exclude(cn_status="cancelled").exists()


def _claim_cancelled(o: MarketOrder) -> bool:
    """마켓 상태와 별개로 클레임으로 끝난 주문 (쿠팡 반품/취소 완료 등) — 단계 취소 유지."""
    return bool(o.claim_type) and o.stage == "cancelled"


async def restage(o: MarketOrder, actor: dict, reason: str, run=None) -> bool:
    """단계를 다시 판정해서 바뀌면 저장 + OrderEvent(kind=stage). 타오바오 구매 등록·삭제 때 부른다."""
    new = decide_stage(market_stage(o), _claim_cancelled(o), await has_purchase(o.id))
    if new == o.stage:
        return False
    old = o.stage
    o.stage = new
    await o.save(update_fields=["stage", "updated_at"])
    await log_event(o, actor, "stage", f"단계 {STAGE_LABEL.get(old, old)} → {STAGE_LABEL.get(new, new)} ({reason})",
                    {**run_tag(run), "stage": {"from": old, "to": new}, "reason": reason}, run)
    return True


async def progress_of(order_ids: list[int]) -> dict[int, dict]:
    """처리 목록의 진행 위치 — 타오바오 구매 / 판매처 발송 / 집운 입고 / 국제 발송 중 지금 칸 (주문마다 가장 앞선 것)."""
    out: dict[int, int] = {}
    for p in await TaobaoPurchase.filter(order_id__in=order_ids, deleted_at=None).exclude(cn_status="cancelled"):
        step = {"ordered": 0, "shipped": 1, "arrived": 2}.get(p.cn_status, 0)
        out[p.order_id] = max(out.get(p.order_id, 0), step)
    jiyun: set[int] = set()      # 집운 기록 있음 — 모바일 '다음 할 일' 판정용 (2026-10-30)
    tracking: set[int] = set()   # 국내 송장 있음
    for j in await JiyunShipment.filter(order_id__in=order_ids, deleted_at=None).exclude(status="cancelled"):
        step = 3 if j.status == "dispatched" else 2
        out[j.order_id] = max(out.get(j.order_id, 0), step)
        jiyun.add(j.order_id)
        if j.kr_tracking_no:
            tracking.add(j.order_id)
    return {oid: {"step": s, "label": PROGRESS_STEPS[s], "total": len(PROGRESS_STEPS),
                  "jiyun": oid in jiyun, "tracking": oid in tracking} for oid, s in out.items()}


async def upsert_line(line: dict, actor: dict, run) -> str:
    """반환: created · changed · same."""
    fp = receiver_fingerprint(line["pccc"], line["receiver_name"], line["phone"], line["zip"])
    fields = {k: line[k] for k in ("order_no", "ship_unit_no", "market_status", "confirmed", "stage", "ordered_at", "paid_at",
                                   "ship_due_at", "product_name", "option_name", "seller_code", "market_product_id",
                                   "market_option_id", "quantity", "unit_price", "total_price", "receiver_name")}
    if "claim_type" in line:   # 네이버만 주문 응답에 클레임이 있다 — 쿠팡은 반품/취소 요청 목록으로 따로 (apply_claim)
        fields.update({k: line.get(k) for k in CLAIM_FIELDS})
    fields.update(receiver_zip=line["zip"] or None, receiver_hash=fp, last_synced_at=datetime.now(timezone.utc),
                  raw_enc=_enc(json.dumps(line["raw"], ensure_ascii=False, default=str)))
    secret = {"receiver_phone_enc": _enc(line["phone"]), "contact_phone_enc": _enc(line.get("contact_phone")),
              "receiver_address_enc": _enc(line["address"]), "pccc_enc": _enc(line["pccc"])}
    m = MARKET_LABEL[line["market"]]
    o = await MarketOrder.get_or_none(market=line["market"], line_no=line["line_no"])

    if o is None:
        o = await MarketOrder.create(market=line["market"], line_no=line["line_no"], **fields, **secret)
        await issue_code(o, actor, run)
        await log_event(o, actor, "collected", f"{m} 주문 수집 — {line['product_name'][:60]} ×{line['quantity']} ({line['market_status']}){run_suffix(run)}", {
            **run_tag(run), "code": o.code, "market": line["market"], "line_no": line["line_no"], "order_no": line["order_no"], "market_status": line["market_status"],
            "confirmed": line["confirmed"], "quantity": line["quantity"], "total_price": line["total_price"],
            "receiver": {"name": mask_name(line["receiver_name"]), "phone": mask_phone(line["phone"]), "zip": line["zip"]},
        }, run)
        if o.claim_type:
            await _log_claim(o, actor, run, None)
        if o.stage != "cancelled":
            await run_pccc_check(o, actor, "새 주문", run)
        return "created"

    # 단계 = 마켓 상태만이 아니라 타오바오 구매 기록·클레임까지 보고 정한다 (decide_stage)
    fields["stage"] = decide_stage(fields["stage"], _claim_cancelled(o), await has_purchase(o.id))
    diff = {k: [_fmt(getattr(o, k)), _fmt(fields[k])] for k in TRACKED if k in fields and getattr(o, k) != fields[k]}
    claim_before = (o.claim_type, o.claim_status)
    receiver_changed = o.receiver_hash != fp
    for k, v in {**fields, **secret}.items():
        setattr(o, k, v)
    await o.save()
    if not diff and not receiver_changed:
        return "same"
    data = {**run_tag(run), "diff": diff}
    if receiver_changed:
        data["receiver_now"] = {"name": mask_name(line["receiver_name"]), "phone": mask_phone(line["phone"]), "zip": line["zip"]}
    names = {"market_status": "상태", "confirmed": "발주확인", "stage": "단계", "quantity": "수량", "total_price": "금액",
             "claim_type": "클레임", "claim_status": "클레임 상태"}
    parts = [f"{names[k]} {a}→{b}" for k, (a, b) in diff.items() if k in names]
    if receiver_changed:
        parts.append("수취인·통관 정보 바뀜")
    await log_event(o, actor, "changed", f"{m} 주문 변경 — " + ", ".join(parts or ["세부 정보"]) + run_suffix(run), data, run)
    if (o.claim_type, o.claim_status) != claim_before and o.claim_type:
        await _log_claim(o, actor, run, claim_before)
    # 마켓에서 발주확인이 된 걸 수집으로 알게 됨 (AGC 발주확인 버튼으로 보낸 게 아님) — 단계가 보이게 따로 남긴다
    if diff.get("confirmed", [None, None])[1] is True:
        await log_event(o, actor, "market_confirmed", f"{m} 발주확인됨 — 마켓에서 확인 (수집으로 감지, AGC 에서 보낸 것 아님)", {
            "step": "발주확인", "stage": "receive", "source": f"{line['market']}_api", "detected_by": "collect",
            "status": {"from": diff.get("market_status", [o.market_status, o.market_status])[0], "to": line["market_status"]},
        }, run)
    if receiver_changed and o.stage != "cancelled":
        await run_pccc_check(o, actor, "수취인·통관 정보 바뀜", run)
    return "changed"


# ------------------------------------------------------------ 클레임 (취소·반품·교환) — 2026-10-27
async def _log_claim(o: MarketOrder, actor: dict, run, before, extra: dict | None = None) -> None:
    """새 클레임·클레임 상태 변화 = OrderEvent(kind=claim). 주문 접수 화면 알림이 이 기록을 본다."""
    m = MARKET_LABEL[o.market]
    label = CLAIM_LABEL.get(o.claim_type or "", o.claim_type or "")
    done = (extra or {}).get("done")
    head = f"{label} 완료" if done else f"{label} {o.claim_status or ''}".strip()
    await log_event(o, actor, "claim", f"{m} 클레임 — {head}" + (f" ({o.claim_reason})" if o.claim_reason else "") + run_suffix(run), {
        **run_tag(run), "claim_type": o.claim_type, "claim_status": o.claim_status, "claim_at": _fmt(o.claim_at),
        "claim_reason": o.claim_reason, "done": bool(done), "stage": o.stage, "detail": extra or None,
        "before": {"claim_type": before[0], "claim_status": before[1]} if before else None,
    }, run)


def _coupang_claim_reason(rc: dict) -> tuple[str, dict]:
    """사람이 읽는 사유 + 기록용 원본 사유. 판매자 취소(파트너 API 강제 취소)는 '판매자 취소'로 앞에 붙인다."""
    c1, c2 = rc.get("cancelReasonCategory1") or "", rc.get("cancelReasonCategory2") or ""
    reason = rc.get("cancelReason") or rc.get("reasonCodeText") or ""
    by = "판매자 취소" if ("파트너" in reason or "판매자" in reason) else ("고객 요청" if rc.get("requesterName") else "")
    text = " · ".join(x for x in (by, c2 or c1) if x) or reason or None
    return text, {"category1": c1, "category2": c2, "reason": reason, "reason_code": rc.get("reasonCode"),
                  "receipt_id": rc.get("receiptId"), "receipt_type": rc.get("receiptType"), "receipt_status": rc.get("receiptStatus")}


async def apply_coupang_claims(start: datetime, end: datetime, actor: dict, run, order_no: str | None = None) -> int:
    """쿠팡 반품/취소 요청 목록 → 해당 주문 줄에 클레임 표시. 반환: 바뀐 주문 줄 수.
    - CANCEL (cancelType=CANCEL): 결제완료에서 바로 취소 → 취소, 단계 취소
    - STOP_SHIPPING (RU) · RETURN (UC): 요청 — 단계는 그대로 (판매자 처리 필요)
    - DONE (CC, 완료): returnItems.releaseStatus=S(출고중지완료 = 출고 전) → 취소 완료, 아니면 반품 완료 · 단계 취소
    order_no 를 주면 그 주문만."""
    receipts = await mc.coupang_claims(start, end)
    changed = 0
    for rc in receipts:
        if order_no and str(rc.get("orderId") or "") != order_no:
            continue
        kind = rc.get("_claim") or "RETURN"
        rstatus = str(rc.get("receiptStatus") or rc.get("_status") or "") or None
        at = _dt(rc.get("createdAt"))
        reason, reason_raw = _coupang_claim_reason(rc)
        for it in rc.get("returnItems") or [{}]:
            if kind == "DONE":
                ctype = "CANCEL" if str(it.get("releaseStatus") or "") == "S" else "RETURN"
            else:
                ctype = kind
            done = kind in ("CANCEL", "DONE")
            qs = MarketOrder.filter(market="coupang", order_no=str(rc.get("orderId") or ""))
            if it.get("vendorItemId"):
                qs = qs.filter(market_option_id=str(it["vendorItemId"]))
            for o in await qs:
                before = (o.claim_type, o.claim_status)
                if before == (ctype, rstatus) and o.claim_reason == reason and (not done or o.stage == "cancelled"):
                    continue
                o.claim_type, o.claim_status, o.claim_at, o.claim_reason = ctype, rstatus, at or o.claim_at, reason
                fields = ["claim_type", "claim_status", "claim_at", "claim_reason", "updated_at"]
                if done and o.stage != "cancelled":
                    o.stage = "cancelled"
                    fields.append("stage")
                await o.save(update_fields=fields)
                await _log_claim(o, actor, run, before, {**reason_raw, "release_status": it.get("releaseStatus"), "done": done})
                changed += 1
    return changed


# ------------------------------------------------------------ 쿠팡 실제 정산액 (매출내역) — 2026-10-27
REVENUE_EVERY = timedelta(hours=6)       # 자동 수집 5분마다 부르지 않게 — 수동 수집이면 바로
REVENUE_DAYS = 31
_revenue_last: dict = {"at": None}


async def apply_coupang_revenue(actor: dict, run, force: bool = False) -> int:
    """구매확정 등으로 매출 인식된 쿠팡 주문의 실제 정산액을 주문 줄에 붙인다. 반환: 바뀐 줄 수."""
    now = datetime.now(timezone.utc)
    if not force and _revenue_last["at"] and now - _revenue_last["at"] < REVENUE_EVERY:
        return 0
    _revenue_last["at"] = now
    today = now.astimezone(KST).date()
    rows = await mc.coupang_revenue((today - timedelta(days=REVENUE_DAYS)).isoformat(), (today - timedelta(days=1)).isoformat())
    sums: dict[tuple, dict] = {}
    for r in rows:
        for it in r.get("items") or []:
            key = (str(r.get("orderId") or ""), str(it.get("vendorItemId") or ""))
            s = sums.setdefault(key, {"amount": 0, "date": r.get("settlementDate") or r.get("recognitionDate")})
            s["amount"] += _units(it.get("settlementAmount"))
    changed = 0
    for (order_no, item_id), s in sums.items():
        qs = MarketOrder.filter(market="coupang", order_no=order_no)
        if item_id:
            qs = qs.filter(market_option_id=item_id)
        for o in await qs:
            if o.settlement_actual == s["amount"]:
                continue
            before = o.settlement_actual
            o.settlement_actual = s["amount"]
            try:
                o.settlement_date = datetime.fromisoformat(str(s["date"])[:10]).date() if s["date"] else o.settlement_date
            except ValueError:
                pass
            await o.save(update_fields=["settlement_actual", "settlement_date", "updated_at"])
            await log_event(o, actor, "settled", f"쿠팡 정산액 확인 — {s['amount']:,}원" + run_suffix(run), {
                **run_tag(run), "settlement": {"from": before, "to": s["amount"]}, "settlement_date": s["date"], "source": "coupang_revenue_history",
            }, run)
            changed += 1
    return changed


# ------------------------------------------------------------ 한 주문만 다시 보기 · 발주확인 시각
async def refresh_order(o: MarketOrder, actor: dict, reason: str) -> MarketOrder:
    """이 주문 하나만 마켓에서 바로 다시 받아 저장한다 (바뀐 게 있으면 changed · market_confirmed 기록).
    마켓에서 바로 한 발주확인을 AGC 가 아직 모를 때 — 예: 타오바오 구매 등록 직전."""
    if o.market == "coupang":
        try:
            box = await mc.coupang_ordersheet(o.ship_unit_no)
        except mc.MarketApiError as e:
            # 쿠팡은 취소·반품된 발주서를 400 "해당 주문이 취소 또는 반품되었습니다." 로 돌려준다 → 취소로 바꾸고 사유 보강
            if "취소 또는 반품" not in str(e):
                raise
            await mark_coupang_gone(o, actor, str(e))
            return await MarketOrder.get(id=o.id)
        lines = parse_coupang(box) if box else []
    elif o.market == "shop":
        row = await so.shop_order(o.order_no)
        lines = so.parse_shop(row) if row else []
    else:
        items = await mc.naver_product_orders([o.ship_unit_no])
        lines = [ln for it in items for ln in parse_naver(it)]
    for ln in lines:
        if ln["line_no"] == o.line_no:
            await upsert_line(ln, actor, None)
    fresh = await MarketOrder.get(id=o.id)
    logger.info(f"주문 다시 보기: order_id={o.id} reason={reason} confirmed={fresh.confirmed}")
    return fresh


async def mark_coupang_gone(o: MarketOrder, actor: dict, message: str) -> None:
    """발주서 조회가 '취소 또는 반품되었습니다' 를 줄 때 — 단계 취소 + 반품/취소 목록에서 사유를 찾아 채운다."""
    if o.stage != "cancelled":
        before = (o.claim_type, o.claim_status)
        o.stage = "cancelled"
        o.claim_type = o.claim_type or "CANCEL"
        o.claim_status = o.claim_status or "CANCELED_OR_RETURNED"
        await o.save(update_fields=["stage", "claim_type", "claim_status", "updated_at"])
        await _log_claim(o, actor, None, before, {"done": True, "source": "coupang_ordersheet", "message": message[:200]})
    now = datetime.now(timezone.utc)
    since = max((o.paid_at or o.ordered_at or now) - timedelta(days=1), now - MAX_RANGE)
    try:
        await apply_coupang_claims(since, now, actor, None, order_no=o.order_no)
    except mc.MarketApiError as e:
        logger.warning(f"쿠팡 취소 사유 보강 실패: order_id={o.id} {str(e)[:200]}")


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
            if market == "shop":
                lines = [ln for row in await so.shop_orders_since(start, end) for ln in so.parse_shop(row)]
            elif market == "naver":
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
            if market == "coupang":   # 취소·반품 요청은 발주서 목록에 안 나온다 → 따로
                run.changed += await apply_coupang_claims(start, end, actor, run)
                try:   # 실제 정산액 — 실패해도 주문 수집은 성공으로 둔다
                    run.changed += await apply_coupang_revenue(actor, run, force=trigger != "poller")
                except mc.MarketApiError as e:
                    logger.warning(f"쿠팡 매출내역 실패: run={run.id} {str(e)[:200]}")
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
        try:   # 출고된 집운 기록의 통관 진행 (H B/L) — 자사몰 고객 화면 통관 단계
            from services.order.customs import refresh_customs
            await refresh_customs()
        except Exception:
            logger.exception("통관 진행 조회 실패")
        try:   # FIN 지출 원장 — 바뀐 줄만 · 지난번 실패분 다시 (2026-10-30)
            from services.finance.fin_expense import sync_all
            await sync_all()
        except Exception:
            logger.exception("FIN 지출 보내기 실패")


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


# ------------------------------------------------------------ 금액 — 총액 · 할인(부담 주체) · 고객 결제 · 수수료 · 정산 (2026-10-27)
def _units(v) -> int:
    """쿠팡 금액 {'units': 18400, 'nanos': 0} · 숫자 · None → 정수 원."""
    if isinstance(v, dict):
        return int(v.get("units") or 0)
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _coupang_fee_rate() -> float:
    from core.pricing_config import DEFAULT_FEE_RATES, Platform
    r = DEFAULT_FEE_RATES[Platform.COUPANG]
    return float(r["platform_fee_rate"]) + float(r["payment_fee_rate"] or 0)


def amount_of(o: MarketOrder, raw: dict | None) -> dict | None:
    """마켓 원본에서 금액 칸을 만든다 (저장된 raw 만 씀, 새 호출 없음).
    total 판매가(총액) · discount 할인 합계 · discount_market 마켓 부담 · discount_seller 판매자 부담(우리 몫이 깎임)
    · paid 고객 결제 · fee 수수료 · fee_detail [{label, amount}] · settlement 정산 예정 · estimated (수수료율로 계산했으면 true)"""
    if not raw:
        return None
    if o.market == "shop":   # 자사몰 — 할인 없음, 결제 수수료 1% 추정 (카카오페이·네이버페이)
        from core.pricing_config import DEFAULT_FEE_RATES, Platform
        rate = float(DEFAULT_FEE_RATES[Platform.SHOP]["payment_fee_rate"])
        total = o.total_price or 0
        fee = round(total * rate / 100)
        return {"total": total, "discount": 0, "discount_market": 0, "discount_seller": 0, "paid": total, "fee": fee,
                "fee_detail": [{"label": "결제", "amount": fee}], "fee_rate": rate, "settlement": total - fee,
                "estimated": True, "actual": False}
    if o.market == "naver":
        po = raw.get("productOrder") or {}
        total = _units(po.get("totalProductAmount"))
        discount = _units(po.get("productDiscountAmount")) + _units(po.get("deliveryDiscountAmount"))
        seller = _units(po.get("sellerBurdenProductDiscountAmount")) + _units(po.get("sellerBurdenStoreDiscountAmount"))
        fees = [("결제", _units(po.get("paymentCommission"))), ("쇼핑연동", _units(po.get("knowledgeShoppingSellingInterlockCommission"))),
                ("판매", _units(po.get("saleCommission"))), ("채널", _units(po.get("channelCommission")))]
        fees = [(k, v) for k, v in fees if v]
        settle = po.get("expectedSettlementAmount")
        return {"total": total, "discount": discount, "discount_market": max(0, discount - seller), "discount_seller": seller,
                "paid": _units(po.get("totalPaymentAmount")), "fee": sum(v for _, v in fees),
                "fee_detail": [{"label": k, "amount": v} for k, v in fees], "fee_rate": None,
                "settlement": _units(settle) if settle is not None else None, "estimated": False, "actual": False}
    # 쿠팡 — 발주서 orderItems 중 이 줄(vendorItemId). 정산 예정은 발주서에 없어 수수료율로 추정, 매출내역이 오면 실제 값
    items = raw.get("orderItems") or []
    oi = next((x for x in items if str(x.get("vendorItemId")) == str(o.market_option_id)), items[0] if items else {})
    total = _units(oi.get("orderPrice"))
    discount = _units(oi.get("discountPrice"))
    market = _units(oi.get("coupangDiscount"))
    seller = _units(oi.get("instantCouponDiscount")) + _units(oi.get("downloadableCouponDiscount"))
    rate = _coupang_fee_rate()
    fee = round(total * rate / 100)
    actual = o.settlement_actual is not None
    return {"total": total, "discount": discount, "discount_market": market, "discount_seller": seller,
            "paid": total - discount, "fee": fee, "fee_detail": [], "fee_rate": rate,
            "settlement": o.settlement_actual if actual else total - fee - seller, "estimated": not actual, "actual": actual}


def order_dict(o: MarketOrder) -> dict:
    phone, pccc, contact = _dec(o.receiver_phone_enc), _dec(o.pccc_enc), _dec(o.contact_phone_enc)
    from services.order.pccc import mask_pccc
    return {
        "id": o.id, "code": o.code, "market": o.market, "line_no": o.line_no, "order_no": o.order_no, "ship_unit_no": o.ship_unit_no,
        "market_status": o.market_status, "confirmed": o.confirmed, "stage": o.stage,
        "claim_type": o.claim_type, "claim_status": o.claim_status, "claim_at": _fmt(o.claim_at),
        "claim_reason": o.claim_reason,
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
        "amount": amount_of(o, json.loads(_dec(o.raw_enc) or "null")),
        "settlement_date": o.settlement_date.isoformat() if o.settlement_date else None,
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
        prog = await progress_of([o.id for o in rows])
        items = [{**order_dict(o), "progress": prog.get(o.id)} for o in rows]
        return {"items": items, "total": total, "page": page, "size": size,
                "pccc_counts": counts, "last_runs": runs, "poll_minutes": POLL_MINUTES}

    @staticmethod
    async def get(order_id: int) -> dict:
        o = await MarketOrder.get_or_none(id=order_id)
        if not o:
            raise HTTPException(status_code=404, detail="주문을 찾지 못했습니다.")
        events = await OrderEvent.filter(order_id=o.id).order_by("-id").prefetch_related("actor_user")
        raw = json.loads(_dec(o.raw_enc) or "null")
        from services.order.sourcing import order_sourcing   # 순환 import 방지
        return {"order": order_dict(o), "events": [event_dict(e) for e in events], "raw_masked": mask_raw(raw),
                "receiver_full": receiver_full(o),
                "sourcing": await order_sourcing(o)}   # 타오바오에서 살 것 (조사 옵션 × 묶음 수)

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
            if o.market == "shop":
                # 자사몰 — 고객 즉시 취소를 막는다 (자사몰 단계 ordered → preparing). 고객이 먼저 취소했으면 실패
                if not await so.set_shop_stage(o.ship_unit_no, "ordered", "preparing"):
                    row = await so.shop_order(o.ship_unit_no)
                    if row and row["status"] == "cancelled":
                        why = "고객이 이미 취소했습니다"
                    else:
                        why = f"자사몰 주문이 결제 완료 상태가 아닙니다 ({row['status'] if row else '없음'}/{row['stage'] if row else '-'})"
                    raise mc.MarketApiError(why)
                res = {"result": {str(o.ship_unit_no): (True, "자사몰 주문 확인")}}
            elif o.market == "coupang":
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
            elif r.market == "shop":
                r.market_status = "CONFIRMED"
            await r.save(update_fields=["confirmed", "market_status", "updated_at"])
            await log_event(r, actor, "market_confirmed", f"{label} 발주확인 보냄 — 고객 화면 상품준비중", {
                "sent": sent, "received": received,
                "changes": {"confirmed": {"from": before["confirmed"], "to": True},
                            "market_status": {"from": before["market_status"], "to": r.market_status}},
            })
        return await OrderService.get(order_id)

    @staticmethod
    async def mark_delivered(order_id: int, auth: dict) -> dict:
        """자사몰 주문 배송 완료 표시 — 마켓 주문은 마켓이 알려 주지만 자사몰은 사람이 누른다 (국내 송장이 있어야).
        자사몰 단계 preparing → delivered, 같은 주문의 AGC 줄 모두 완료."""
        o = await MarketOrder.get_or_none(id=order_id)
        if not o:
            raise HTTPException(status_code=404, detail="주문을 찾지 못했습니다.")
        if o.market != "shop":
            raise HTTPException(status_code=400, detail="배송 완료 표시는 자사몰 주문만 합니다 (마켓 주문은 마켓 상태로 바뀝니다).")
        if o.market_status == "DELIVERED":
            return {**await OrderService.get(order_id), "already": True}
        rows = await MarketOrder.filter(market="shop", ship_unit_no=o.ship_unit_no)
        if not await JiyunShipment.filter(order_id__in=[r.id for r in rows], deleted_at=None, kr_tracking_no__isnull=False).exclude(kr_tracking_no="").exists():
            raise HTTPException(status_code=409, detail="국내 송장이 있는 집운 기록이 없어 배송 완료로 표시할 수 없습니다.")
        if not await so.set_shop_stage(o.ship_unit_no, "preparing", "delivered"):
            raise HTTPException(status_code=409, detail="자사몰 주문이 주문 확인 상태가 아니라서 배송 완료로 바꿀 수 없습니다.")
        actor = actor_of(auth)
        for r in rows:
            before = r.market_status
            r.market_status = "DELIVERED"
            await r.save(update_fields=["market_status", "updated_at"])
            await log_event(r, actor, "delivered", "자사몰 배송 완료 표시 — 고객 화면 배송 완료",
                            {"changes": {"market_status": {"from": before, "to": "DELIVERED"}}})
            await restage(r, actor, "배송 완료")
        return await OrderService.get(order_id)

    @staticmethod
    async def updates(after: int | None) -> dict:
        """주문 접수 화면 알림용 — after(이벤트 id) 뒤에 생긴 새 주문(collected)·클레임(claim). after 가 없으면 기준 id 만."""
        last = await OrderEvent.all().order_by("-id").first()
        last_id = last.id if last else 0
        if after is None:
            return {"last_event_id": last_id, "new_orders": [], "claims": []}
        evs = await OrderEvent.filter(id__gt=after, kind__in=["collected", "claim"]).order_by("id").limit(100).prefetch_related("order")
        pick = lambda e: {"event_id": e.id, "order_id": e.order_id, "code": e.order.code, "market": e.order.market,
                          "product_name": e.order.product_name, "summary": e.summary, "at": e.created_at.isoformat(),
                          "auto": bool((e.data or {}).get("run", {}).get("auto"))}
        return {"last_event_id": last_id,
                "new_orders": [pick(e) for e in evs if e.kind == "collected"],
                "claims": [pick(e) for e in evs if e.kind == "claim"]}
