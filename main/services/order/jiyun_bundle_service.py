"""집운 묶음 — 받는 사람이 같은 주문 여러 건을 집운 한 번(합포장)으로 (2026-11-11).

규칙 (jiyun-rules.md): 통관은 받는 사람 1명 단위 → 받는 사람(이름 + 우편번호)이 같은 주문만 한 집운에 묶는다.
기록은 지금처럼 주문마다 1건씩 — 집운 번호는 첫 주문이 원래 번호, 다음부터 -2, -3 … (jiyun_service._base_no).
배송비 · 결제 금액 · 원화는 주문별 무게 비율로 나눈다 (무게를 모르면 소포 수 비율). 끝수는 마지막 주문에 맞춘다.
출고 · H B/L · 국내 송장처럼 한 상자에 같은 값은 묶음 전체에 한 번에 넣는다 (update_bundle)."""

import re
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException

from models.order.jiyun import JiyunShipment
from models.order.order import MarketOrder
from models.order.purchase import TaobaoPurchase
from schemas.jiyun import JiyunBundleCreate, JiyunBundleUpdate, JiyunCreate, JiyunUpdate
from services.order.jiyun_service import JiyunService, _base_no, alive, jiyun_dict
from services.order.order_service import _dec, _short_address, receiver_full
from services.order.pccc import mask_name

_norm = lambda s: re.sub(r"\s+", "", s or "")


def _receiver_key(o: MarketOrder) -> tuple[str, str]:
    r = receiver_full(o)
    return _norm(r["name"]), _norm(r["zip"])


def _parcel(no) -> str:
    return str(no or "").strip().upper()


async def candidates(include_test: bool = False) -> list[dict]:
    """집운 보낼 거리 — 창고에 들어왔는데 아직 어느 집운에도 안 묶인 소포를 받는 사람별로.
    같은 사람의 아직 오는 중인 소포도 같이 보여 준다 (다 오면 한 번에 보내려고)."""
    qs = MarketOrder.filter(stage="processing")
    if not include_test:
        qs = qs.filter(is_test=False)
    orders = {o.id: o for o in await qs}
    if not orders:
        return []
    ids = list(orders)
    in_jiyun: dict[int, set] = {}
    for j in await alive().filter(order_id__in=ids).exclude(status="cancelled"):
        in_jiyun.setdefault(j.order_id, set()).update(_parcel(p) for p in (j.packages or []))
    parcels: dict[int, list] = {}
    for p in await TaobaoPurchase.filter(order_id__in=ids, deleted_at=None).exclude(cn_status="cancelled").order_by("id"):
        no = _parcel(p.cn_tracking_no)
        if no and no in in_jiyun.get(p.order_id, set()):
            continue
        parcels.setdefault(p.order_id, []).append({
            "purchase_id": p.id, "taobao_order_no": p.taobao_order_no, "no": no or None,
            "cn_courier": p.cn_courier, "cn_status": p.cn_status,
            "ready": p.cn_status == "arrived" and bool(no),
            "arrived_at": p.arrived_at.isoformat() if p.arrived_at else None,
        })
    groups: dict[tuple, dict] = {}
    for oid, ps in parcels.items():
        o = orders[oid]
        key = _receiver_key(o)
        g = groups.setdefault(key, {"receiver": mask_name(o.receiver_name or ""),
                                    "region": _short_address(_dec(o.receiver_address_enc)) or None,
                                    "orders": []})
        g["orders"].append({
            "id": o.id, "code": o.code, "market": o.market, "product_name": o.product_name,
            "option_name": o.option_name, "quantity": o.quantity, "is_test": o.is_test,
            "has_jiyun": oid in in_jiyun, "parcels": ps,
            "ship_due_at": o.ship_due_at.isoformat() if o.ship_due_at else None,
        })
    out = []
    for g in groups.values():
        ready = sum(1 for o in g["orders"] for p in o["parcels"] if p["ready"])
        if not ready and len(g["orders"]) < 2:   # 혼자 오는 중인 주문은 안 보여 줌 — 여러 건이면 '다 오면 묶음' 으로 미리
            continue
        total = sum(len(o["parcels"]) for o in g["orders"])
        g["orders"].sort(key=lambda o: o["code"] or "")
        out.append({**g, "ready": ready, "coming": total - ready, "key": f"{g['orders'][0]['id']}"})
    out.sort(key=lambda g: (g["coming"] > 0, -g["ready"]))
    return out


def _split(total: Decimal | int | None, weights: list[Decimal], cents: bool) -> list:
    """total 을 weights 비율로 — 끝수는 마지막에 맞춘다. cents=True 면 소수 둘째 자리(위안), 아니면 원."""
    if total is None:
        return [None] * len(weights)
    total = Decimal(str(total))
    q = Decimal("0.01") if cents else Decimal("1")
    s = sum(weights) or Decimal(len(weights))
    ws = weights if sum(weights) else [Decimal(1)] * len(weights)
    parts = [(total * w / s).quantize(q, rounding=ROUND_HALF_UP) for w in ws]
    parts[-1] = total - sum(parts[:-1])
    return parts if cents else [int(p) for p in parts]


async def create_bundle(body: JiyunBundleCreate, auth: dict) -> list[dict]:
    if len(body.orders) < 1:
        raise HTTPException(status_code=400, detail="묶을 주문을 골라주세요.")
    ids = [x.order_id for x in body.orders]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=400, detail="같은 주문이 두 번 들어갔어요.")
    orders = {o.id: o for o in await MarketOrder.filter(id__in=ids)}
    if len(orders) != len(ids):
        raise HTTPException(status_code=404, detail="고객 주문을 찾지 못했습니다.")
    keys = {_receiver_key(orders[i]) for i in ids}
    if len(keys) > 1:
        codes = ", ".join(orders[i].code or str(i) for i in ids)
        raise HTTPException(status_code=409, detail=f"받는 사람이 다른 주문이 섞여 있어요 ({codes}). 받는 사람이 같은 주문만 한 집운에 묶을 수 있어요.")
    base = _base_no(body.jiyun_no)
    nos = [base] + [f"{base}-{i}" for i in range(2, len(ids) + 1)]
    taken = await alive().filter(jiyun_no__in=nos).values_list("jiyun_no", flat=True)
    if taken:
        raise HTTPException(status_code=409, detail=f"집운 번호 {', '.join(taken)} 는 이미 등록돼 있어요.")

    weights = [Decimal(str(x.weight_kg)) if x.weight_kg is not None else None for x in body.orders]
    if any(w is None for w in weights):   # 무게를 다 모르면 소포 수 비율
        weights = [Decimal(len(x.packages) or 1) for x in body.orders]
        per_weight = [None] * len(ids)
    else:
        per_weight = weights
    fees = _split(body.fee_cny, weights, True)
    pays = _split(body.pay_amount, weights, True)
    krws = _split(body.charged_krw, weights, False)
    codes = "·".join(orders[i].code or str(i) for i in ids)
    total_w = sum(w for w in per_weight if w is not None) if per_weight[0] is not None else body.total_weight_kg
    head = (f"{len(ids)}건({codes}) 한 집운으로 합포장({base})"
            + (f". 총 {total_w}kg" if total_w is not None else "")
            + (f" ¥{body.fee_cny}" if body.fee_cny is not None else "")
            + (f" · {body.charged_krw:,}원" if body.charged_krw is not None else ""))
    common = body.model_dump(exclude={"orders", "jiyun_no", "fee_cny", "pay_amount", "charged_krw", "total_weight_kg", "memo",
                                       "packages", "weight_kg"})
    created = []
    for i, x in enumerate(body.orders):
        share = (f" 이 주문 몫 {per_weight[i]}kg → 무게 비율" if per_weight[i] is not None else " 소포 수 비율로 나눔")
        memo = head + "." + share + (f" ¥{fees[i]}" if fees[i] is not None else "") + (f" · {krws[i]:,}원" if krws[i] is not None else "")
        if body.memo:
            memo += f" / {body.memo}"
        one = JiyunCreate(**common, order_id=x.order_id, jiyun_no=nos[i], packages=x.packages,
                          weight_kg=per_weight[i], fee_cny=fees[i], pay_amount=pays[i], charged_krw=krws[i], memo=memo[:2000])
        created.append(await JiyunService.create(one, auth))
    return created


async def bundle_of(jiyun_id: int) -> list[JiyunShipment]:
    j = await alive().get_or_none(id=jiyun_id)
    if not j:
        raise HTTPException(status_code=404, detail="집운 기록을 찾지 못했습니다.")
    base = _base_no(j.jiyun_no)
    return [x for x in await alive().filter(jiyun_no__startswith=base).order_by("id") if _base_no(x.jiyun_no) == base]


async def get_bundle(jiyun_id: int) -> list[dict]:
    return [await jiyun_dict(x) for x in await bundle_of(jiyun_id)]


async def update_bundle(jiyun_id: int, body: JiyunBundleUpdate, auth: dict) -> list[dict]:
    """한 상자에 같은 값(상태 · 출고 · H B/L · 국내 택배사·송장 · 청구 확인)을 묶음 전체에."""
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
    out = []
    for x in await bundle_of(jiyun_id):
        out.append(await JiyunService.update(x.id, JiyunUpdate(**data), auth))
    return out
