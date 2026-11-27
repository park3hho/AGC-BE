"""집운 묶음 번호 PRE_LP… (2026-11-16 사용자: "가장 빠른 주문번호로 묶지 말고 묶음 번호를 따로. 다음 날 연속으로 시켜도 같이 묶이게.
집운 번호(LP)는 물류 주문마다 생기니 묶음 번호와 1:1. PRE_LP + 36^10 으로 매기고, 주문을 유동적으로 추가하다가 확정되면 결제하고 LP 번호를 붙이자").

- 새 주문이 들어오면 같은 받는 사람(이름 + 우편번호)의 open 묶음에 합류 — 날짜 상관없이. 예상 무게 합이
  JIYUN_BUNDLE_MAX_KG(기본 25kg, 30kg 넘으면 大件操作费 ¥60 · jiyun-rules)를 넘게 되면 새 묶음을 연다.
- 상태: open → confirmed(확정 · 결제 대기, 합류 잠금) → paid(집운 결제 기록이 생김 · LP 번호) → dispatched(출고) → done / cancelled.
  paid 이후는 사실(집운 기록 · 주문 단계)로 정한다 — recompute().
- 취소된 주문은 결제 전(open · confirmed) 묶음에서 빠진다. 결제 뒤에는 기록으로 남긴다.
- market_order.bundle_key = 묶음 code (예전 화면 · 30분 점검 · 홈 할 일 호환)."""

import logging
import os
import re
import secrets
import string
from datetime import datetime, timezone

from fastapi import HTTPException

from models.order.bundle import JiyunBundle
from models.order.jiyun import JiyunShipment
from models.order.order import MarketOrder
from models.order.purchase import TaobaoPurchase

logger = logging.getLogger(__name__)
MAX_G = int(float(os.getenv("JIYUN_BUNDLE_MAX_KG", "25")) * 1000)
ALPHABET = string.ascii_uppercase + string.digits
OPEN = ("open", "confirmed")
STATUS_LABEL = {"open": "모으는 중", "confirmed": "확정 · 결제 대기", "paid": "집운 결제", "dispatched": "출고",
                "done": "배송 완료", "cancelled": "취소"}
_norm = lambda s: re.sub(r"\s+", "", s or "")


def receiver_key(o: MarketOrder) -> str:
    return f"{_norm(o.receiver_name)}|{_norm(o.receiver_zip)}"


def _base_no(no: str | None) -> str:
    return re.sub(r"-\d{1,2}$", "", (no or "").strip())


DIGITS36 = string.digits + string.ascii_uppercase        # 0-9 → A-Z 순서 (36진수)


def _b36(n: int, width: int = 10) -> str:
    s = ""
    while n:
        n, r = divmod(n, 36)
        s = DIGITS36[r] + s
    return s.rjust(width, "0")


async def new_code() -> str:
    """PRE_LP + 36진수 10자리 일련번호, 0000000000 부터 차례로 (2026-11-17 사용자: "0부터 시작해야해")."""
    last = 0 - 1
    for c in await JiyunBundle.filter(code__startswith="PRE_LP").values_list("code", flat=True):
        suf = c[6:]
        if len(suf) == 10 and all(ch in DIGITS36 for ch in suf):
            last = max(last, int(suf, 36))
    n = last + 1
    while await JiyunBundle.exists(code="PRE_LP" + _b36(n)):
        n += 1
    return "PRE_LP" + _b36(n)


async def order_weight_g(o: MarketOrder) -> int | None:
    """주문 1건 예상 무게 — 조사 옵션 용량 × 타오바오에서 살 개수 (+상자). 못 구하면 None."""
    try:
        from models.product.product import Product
        from services.order.sourcing import order_sourcing
        from services.pricing.shipping_service import option_shipping
        s = await order_sourcing(o)
        if not s or not s.get("option1"):
            return None
        p = await Product.get_or_none(id=s["product_id"])
        sh = option_shipping(s["option1"], s.get("option2"), "tea" if p and p.category == "tea" else "beverage")
        w = sh.get("weight_g") or sh.get("dim_weight_g")
        return int(w) * int(s.get("taobao_qty") or o.quantity or 1) if w else None
    except Exception as e:
        logger.warning(f"묶음 무게 계산 실패 {o.code}: {type(e).__name__}")
        return None


async def _members(b: JiyunBundle, alive_only: bool = True) -> list[MarketOrder]:
    qs = MarketOrder.filter(jiyun_bundle_id=b.id)
    if alive_only:
        qs = qs.exclude(stage="cancelled")
    return await qs.order_by("id")


async def _attach(o: MarketOrder, b: JiyunBundle) -> None:
    o.jiyun_bundle_id = b.id
    o.bundle_key = b.code
    await o.save(update_fields=["jiyun_bundle_id", "bundle_key", "updated_at"])


# ── 상자 구성 다시 짜기 (2026-11-27 사용자: "자사 집운번호를 30kg 단위 상자마다 하나씩, 어떤 제품이 들어갈지 FE 에 보여 주면 그걸로 집운 결제") ──
#   같은 받는 사람의 open 묶음(결제 전 · 확정 전)에 든 주문 단위를 jiyun_estimate.pack 으로 가장 싼 상자 구성으로 나눈다.
#   상자 1개 = 묶음 번호 1개. 기존 open 번호는 그대로 재사용(번호가 자꾸 바뀌지 않게), 모자라면 새 번호.
#   한 주문이 여러 상자로 나뉘면(예: 15병 × 4 = 33.8kg) 주문의 묶음(FK)은 첫 상자, 각 상자의 contents 에 넣을 개수.
#   확정(confirmed) 이후 묶음은 건드리지 않는다.
async def replan(key: str, is_test: bool) -> list[JiyunBundle]:
    from services.pricing import jiyun_estimate as je
    bundles = await JiyunBundle.filter(receiver_key=key, is_test=is_test, status="open").order_by("id")
    if not bundles:
        return []
    orders: list[MarketOrder] = []
    for b in bundles:
        if await JiyunShipment.filter(bundle_id=b.id, deleted_at=None).exclude(status="cancelled").exists():
            return bundles   # 이미 집운 결제가 시작된 묶음이 있으면 그대로 (사람이 진행 중)
        orders += [m for m in await _members(b) if m not in orders]
    orders.sort(key=lambda m: m.id)
    pool: list[tuple[MarketOrder, int, int]] = []           # (주문, 옵션, 단위 수)
    unknown: list[MarketOrder] = []
    for m in orders:
        it = je.items_from_orders([{"id": m.id, "seller_code": m.seller_code, "quantity": m.quantity}])
        if it:
            pool.append((m, it[0][0], it[0][1]))
        else:
            unknown.append(m)
    if not pool:
        return bundles
    ctx = await je.load_context()
    agg: dict[int, int] = {}
    for _, oid, n in pool:
        agg[oid] = agg.get(oid, 0) + n
    plan = je.pack(ctx, list(agg.items()))
    boxes = sorted(plan["boxes"], key=lambda b: -b["weight_g"])
    # 상자마다 옵션 개수를 주문 순서대로 채운다
    left = [[m, oid, n] for m, oid, n in pool]
    while len(bundles) < len(boxes):
        bundles.append(await JiyunBundle.create(code=await new_code(), receiver_key=key, is_test=is_test, status="open"))
    first_box: dict[int, JiyunBundle] = {}
    for bx, b in zip(boxes, bundles):
        contents = []
        for oid, need in bx["items"]:
            for row in left:
                if need <= 0:
                    break
                m, roid, have = row
                if roid != oid or have <= 0:
                    continue
                take = min(have, need)
                row[2] -= take
                need -= take
                o = ctx.opts.get(oid)
                contents.append({"order_id": m.id, "order_code": m.code, "option_id": oid, "units": take,
                                 "label": f"{o.title} · {o.label}"[:120] if o else m.product_name[:120]})
                first_box.setdefault(m.id, b)
        b.contents = contents
        b.est_fee_cny = bx["fee_cny"]
        b.est_weight_g = bx["weight_g"]
        await b.save(update_fields=["contents", "est_fee_cny", "est_weight_g", "updated_at"])
    for m in unknown:   # 옵션을 못 읽은 주문은 가장 가벼운 상자에
        first_box.setdefault(m.id, bundles[len(boxes) - 1])
    for m in orders:
        b = first_box.get(m.id)
        if b and m.jiyun_bundle_id != b.id:
            await _attach(m, b)
    for b in bundles[len(boxes):]:   # 남는 빈 open 묶음
        b.contents, b.est_fee_cny = [], None
        await b.save(update_fields=["contents", "est_fee_cny", "updated_at"])
    for b in bundles:
        await recompute(b, plan_ok=True)
    return bundles[:len(boxes)]


async def assign(o: MarketOrder) -> JiyunBundle | None:
    """새 주문을 묶음에 — 같은 받는 사람의 open 묶음에 넣고, 그 사람 open 묶음 전체를 가장 싼 상자 구성으로 다시 짠다."""
    if o.jiyun_bundle_id:
        return await JiyunBundle.get_or_none(id=o.jiyun_bundle_id)
    if not o.code or o.stage in ("done", "cancelled"):
        return None
    key = receiver_key(o)
    w = await order_weight_g(o) or 0
    target = None
    if _norm(o.receiver_name) and _norm(o.receiver_zip):
        for b in await JiyunBundle.filter(receiver_key=key, is_test=o.is_test, status="open").order_by("id"):
            if (b.est_weight_g or 0) + w <= MAX_G or not await _members(b):
                target = b
                break
    if not target:
        target = await JiyunBundle.create(code=await new_code(), receiver_key=key, is_test=o.is_test, status="open")
    await _attach(o, target)
    await recompute(target)
    if _norm(o.receiver_name) and _norm(o.receiver_zip):
        try:
            await replan(key, o.is_test)
            await o.refresh_from_db()
            return await JiyunBundle.get_or_none(id=o.jiyun_bundle_id) or target
        except Exception as e:   # 구성 계산이 실패해도 묶음 배정은 살린다
            logger.warning(f"상자 구성 계산 실패 {o.code}: {type(e).__name__}: {e}")
    return target


async def recompute(b: JiyunBundle, plan_ok: bool = False) -> JiyunBundle:
    """사실로 상태 다시 정하기 — 취소 주문 빼기(결제 전) · 집운 기록 연결 · LP 번호 · 예상 무게 · 상태."""
    every = await _members(b, alive_only=False)
    dropped = False
    if b.status in OPEN:   # 결제 전 — 취소된 주문은 묶음에서 뺀다
        for m in every:
            if m.stage == "cancelled":
                m.jiyun_bundle_id = None
                m.bundle_key = None
                await m.save(update_fields=["jiyun_bundle_id", "bundle_key", "updated_at"])
                dropped = True
    if dropped and b.status == "open" and not plan_ok:   # 빠진 주문이 있으면 상자 구성 다시
        try:
            await replan(b.receiver_key, b.is_test)
            await b.refresh_from_db()
        except Exception as e:
            logger.warning(f"상자 구성 다시 계산 실패 {b.code}: {type(e).__name__}")
    members = await _members(b)
    ids = [m.id for m in members] or [m.id for m in every]
    ships = await JiyunShipment.filter(order_id__in=ids, deleted_at=None).exclude(status="cancelled").order_by("id") if ids else []
    for j in ships:
        if j.bundle_id != b.id:
            j.bundle_id = b.id
            await j.save(update_fields=["bundle_id", "updated_at"])
    if not (b.status == "open" and b.contents):   # 상자 구성이 있으면 그 무게(replan)가 정본
        weights = [await order_weight_g(m) for m in members]
        b.est_weight_g = sum(x for x in weights if x) or None
    now = datetime.now(timezone.utc)
    if ships:
        b.lp_no = b.lp_no or _base_no(ships[0].jiyun_no)
        b.paid_at = b.paid_at or ships[0].requested_at or ships[0].created_at
        if members and all(m.stage == "done" for m in members):
            b.status = "done"
        elif all(j.status == "dispatched" for j in ships):
            b.status = "dispatched"
            b.dispatched_at = b.dispatched_at or ships[0].dispatched_at or now
        else:
            b.status = "paid"
    elif not members and b.status == "open" and b.contents:   # 나뉜 주문의 둘째 상자 (주문 FK 는 첫 상자)
        pass
    elif not members:
        b.status = "cancelled"
    elif all(m.stage == "done" for m in members):   # 집운 기록 없이 끝난 예전 주문
        b.status = "done"
    elif b.status not in OPEN:   # 결제 기록이 지워짐 → 결제 대기로
        b.status = "confirmed"
    await b.save()
    return b


async def recompute_for_order(order_id: int) -> None:
    o = await MarketOrder.get_or_none(id=order_id)
    if o and o.jiyun_bundle_id:
        b = await JiyunBundle.get_or_none(id=o.jiyun_bundle_id)
        if b:
            await recompute(b)


async def sync_all() -> int:
    """수집 주기마다 — 끝나지 않은 묶음을 다시 계산 (취소 반영 · 출고 · 완료)."""
    n = 0
    for b in await JiyunBundle.exclude(status__in=["done", "cancelled"]):
        before = b.status
        await recompute(b)
        n += int(before != b.status)
    return n


# ------------------------------------------------------------ 화면용
def _receiver_label(key: str | None) -> str:
    """받는 사람 표시 — 이름 가림 · 우편번호 (예: 김*수 · 31452). 결제 대기 상자 받는 사람별 묶음용."""
    from services.order.pccc import mask_name
    name, _, zip_ = (key or "").partition("|")
    return " · ".join(x for x in (mask_name(name) if name else "", zip_) if x) or "받는 사람 미확인"

async def bundle_dict(b: JiyunBundle, detail: bool = False) -> dict:
    members = await _members(b, alive_only=not detail)
    ids = [m.id for m in members]
    buys: dict[int, list] = {}
    for p in await TaobaoPurchase.filter(order_id__in=ids, deleted_at=None).exclude(cn_status="cancelled").order_by("id"):
        buys.setdefault(p.order_id, []).append(p)
    total = sum(max(1, len(buys.get(i, []))) for i in ids if any(m.id == i and m.stage != "cancelled" for m in members))
    arrived = sum(1 for i in ids for p in buys.get(i, []) if p.cn_status == "arrived")
    d = {"id": b.id, "code": b.code, "status": b.status, "status_label": STATUS_LABEL.get(b.status, b.status),
         "lp_no": b.lp_no, "jiyun_trade_id": b.jiyun_trade_id, "est_weight_g": b.est_weight_g, "max_weight_g": MAX_G,
         "is_test": b.is_test, "size": sum(1 for m in members if m.stage != "cancelled"),
         "codes": [m.code for m in members if m.stage != "cancelled"],
         "arrived": arrived, "total": total, "ready": total > 0 and arrived >= total,
         "created_at": b.created_at.isoformat(), "confirmed_at": b.confirmed_at.isoformat() if b.confirmed_at else None,
         "paid_at": b.paid_at.isoformat() if b.paid_at else None, "memo": b.memo,
         "receiver_label": _receiver_label(b.receiver_key),
         "contents": b.contents or [], "est_fee_cny": float(b.est_fee_cny) if b.est_fee_cny is not None else None}
    if not d["codes"] and d["contents"]:   # 나뉜 주문의 둘째 상자
        d["codes"] = sorted({c["order_code"] for c in d["contents"]})
        d["size"] = len(d["codes"])
    if detail:
        from services.order.pccc import mask_name
        ships = await JiyunShipment.filter(bundle_id=b.id, deleted_at=None).order_by("id")
        d["receiver"] = mask_name(members[0].receiver_name or "") if members else ""
        d["orders"] = [{
            "id": m.id, "code": m.code, "market": m.market, "stage": m.stage, "product_name": m.product_name,
            "option_name": m.option_name, "quantity": m.quantity, "weight_g": await order_weight_g(m),
            "ordered_at": m.ordered_at.isoformat() if m.ordered_at else None,
            "parcels": [{"purchase_id": p.id, "taobao_order_no": p.taobao_order_no, "cn_status": p.cn_status,
                         "cn_tracking_no": p.cn_tracking_no, "arrived_at": p.arrived_at.isoformat() if p.arrived_at else None}
                        for p in buys.get(m.id, [])],
        } for m in members]
        d["shipments"] = [{"id": j.id, "order_id": j.order_id, "jiyun_no": j.jiyun_no, "status": j.status,
                           "fee_cny": str(j.fee_cny) if j.fee_cny is not None else None, "charged_krw": j.charged_krw,
                           "hbl": j.hbl, "kr_tracking_no": j.kr_tracking_no} for j in ships]
    return d


async def list_bundles(status: str | None = None, include_test: bool = False) -> list[dict]:
    qs = JiyunBundle.all()
    if status == "active":
        qs = qs.filter(status__in=["open", "confirmed", "paid", "dispatched"])
    elif status:
        qs = qs.filter(status=status)
    if not include_test:
        qs = qs.filter(is_test=False)
    return [await bundle_dict(b) for b in await qs.order_by("-id").limit(300)]


async def get_bundle(code: str) -> dict:
    b = await JiyunBundle.get_or_none(code=code.strip().upper())
    if not b:
        raise HTTPException(status_code=404, detail="집운 묶음을 찾지 못했어요.")
    return await bundle_dict(b, detail=True)


async def set_status(code: str, confirm: bool) -> dict:
    b = await JiyunBundle.get_or_none(code=code.strip().upper())
    if not b:
        raise HTTPException(status_code=404, detail="집운 묶음을 찾지 못했어요.")
    if b.status not in OPEN:
        raise HTTPException(status_code=409, detail=f"이미 {STATUS_LABEL.get(b.status)} 상태라 바꿀 수 없어요.")
    b.status = "confirmed" if confirm else "open"
    b.confirmed_at = datetime.now(timezone.utc) if confirm else None
    await b.save(update_fields=["status", "confirmed_at", "updated_at"])
    return await bundle_dict(b, detail=True)


async def update_fields(code: str, data: dict) -> dict:
    """에이전트용 — LP 번호 · 집운 결제 주문번호(tradeId) · 메모 고치기. 바꾼 뒤 상태 다시 계산."""
    b = await JiyunBundle.get_or_none(code=code.strip().upper())
    if not b:
        raise HTTPException(status_code=404, detail="집운 묶음을 찾지 못했어요.")
    for k in ("lp_no", "jiyun_trade_id", "memo"):
        if k in data:
            setattr(b, k, (data[k] or "").strip() or None)
    await b.save()
    return await bundle_dict(await recompute(b), detail=True)


async def by_order(order_code: str) -> dict:
    o = await MarketOrder.get_or_none(code=order_code.strip().upper())
    if not o or not o.jiyun_bundle_id:
        raise HTTPException(status_code=404, detail="그 주문의 집운 묶음이 없어요.")
    return await bundle_dict(await JiyunBundle.get(id=o.jiyun_bundle_id), detail=True)


async def move(order_id: int, target: str | None) -> JiyunBundle:
    """주문을 다른 묶음으로 (target = 묶음 code PRE_LP… 또는 그 묶음의 주문 코드 OR-…) · 없으면 따로(새 묶음)."""
    o = await MarketOrder.get_or_none(id=order_id)
    if not o:
        raise HTTPException(status_code=404, detail="주문을 찾지 못했습니다.")
    if await JiyunShipment.filter(order_id=o.id, deleted_at=None).exclude(status="cancelled").exists():
        raise HTTPException(status_code=409, detail="이미 집운을 결제한 주문은 묶음을 바꿀 수 없어요.")
    old = await JiyunBundle.get_or_none(id=o.jiyun_bundle_id) if o.jiyun_bundle_id else None
    if old and old.status not in OPEN:
        raise HTTPException(status_code=409, detail="결제된 묶음의 주문은 옮길 수 없어요.")
    if target:
        t = target.strip().upper()
        if t.startswith("PRE_LP"):
            nb = await JiyunBundle.get_or_none(code=t)
        else:
            head = await MarketOrder.get_or_none(code=t)
            nb = await JiyunBundle.get_or_none(id=head.jiyun_bundle_id) if head and head.jiyun_bundle_id else None
        if not nb:
            raise HTTPException(status_code=404, detail=f"묶음 {target} 를 찾지 못했어요.")
        if nb.receiver_key != receiver_key(o):
            raise HTTPException(status_code=409, detail="받는 사람이 다른 묶음에는 넣을 수 없어요 (통관이 받는 사람 1명 단위).")
        if nb.status not in OPEN:
            raise HTTPException(status_code=409, detail="결제된 묶음에는 넣을 수 없어요.")
    else:
        nb = await JiyunBundle.create(code=await new_code(), receiver_key=receiver_key(o), is_test=o.is_test, status="open")
    await _attach(o, nb)
    await recompute(nb)
    if old and old.id != nb.id:
        await recompute(old)
    return nb


async def backfill() -> dict:
    """예전 주문(bundle_key = 주문 코드)을 묶음으로 — 한 번만. bundle_key 묶음 → 묶음 1개, bundle_key 없는 주문은
    같은 집운 번호(-2/-3 뗀)끼리, 그것도 없으면 주문 1건이 묶음 1개. 취소되고 집운도 없는 주문은 건너뛴다."""
    orders = await MarketOrder.filter(jiyun_bundle_id=None).exclude(code=None).order_by("id")
    ships: dict[int, list] = {}
    for j in await JiyunShipment.filter(deleted_at=None).exclude(status="cancelled"):
        ships.setdefault(j.order_id, []).append(j)
    groups: dict[str, list] = {}
    for o in orders:
        if o.id in ships:   # 이미 결제된 건 같은 LP 번호끼리가 사실
            key = "L:" + _base_no(ships[o.id][0].jiyun_no)
        elif o.bundle_key and not o.bundle_key.startswith("PRE_LP"):
            key = "K:" + o.bundle_key
        elif o.stage == "cancelled":
            continue
        else:
            key = "O:" + o.code
        groups.setdefault(key, []).append(o)
    made = 0
    for key, ms in groups.items():
        alive = [m for m in ms if m.stage != "cancelled"] or ms
        b = await JiyunBundle.create(code=await new_code(), receiver_key=receiver_key(alive[0]), is_test=alive[0].is_test,
                                     status=("paid" if any(m.id in ships for m in ms) else
                                             "open" if alive[0].stage in ("received", "processing") else "confirmed"),
                                     memo=f"예전 묶음 {key[2:]} 에서 옮김 (2026-11-16)")
        for m in ms:
            await _attach(m, b)
        await recompute(b)
        made += 1
    return {"bundles": made, "orders": len(orders)}
