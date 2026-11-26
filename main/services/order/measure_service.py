"""옵션별 실측 (2026-11-18) — models/order/measure.py

- 기록: 집운 창고가 잰 상자 무게 · 가로 · 세로 · 높이를 주문(또는 집운 기록)에 붙여 남긴다.
  주문 판매자 상품코드(SKU)로 제품 · 옵션 · 묶음 수를 찾고, units = 묶음 수 × 주문 수량.
  같은 집운 번호(-2/-3 뗀 것)나 같은 집운 묶음에 다른 주문이 있으면 합포장(mixed) — 평균에서 뺀다.
- 평균: (옵션, units) 별 실측 평균 → 가격 책정 배송비가 추정 대신 먼저 쓴다 (shipping_service.apply_measured).
- 예전 기록 채우기: 무게가 있는 집운 기록 중 합포장이 아닌 것은 무게만 backfill 로 넣는다 (크기 없음).
비공개 — 원가·운임 구조. 개인정보(수취인)는 다루지 않는다.
"""
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException

from models.order.jiyun import JiyunShipment
from models.order.measure import OptionMeasure
from models.order.order import MarketOrder
from models.product.product import Product
from services.order.stock_service import parse_sku

SOURCES = {"jiyun": "집운 창고", "manual": "직접 입력", "backfill": "예전 집운 기록 (무게만)"}
_SUFFIX = re.compile(r"-\d+$")


def alive():
    return OptionMeasure.filter(deleted_at=None)


def _num(v) -> Optional[float]:
    return float(v) if v is not None else None


def _base_no(no: Optional[str]) -> str:
    return _SUFFIX.sub("", (no or "").strip())


def measure_dict(m: OptionMeasure) -> dict:
    return {
        "id": m.id, "product_id": m.product_id, "option_id": m.option_id, "sku": m.sku, "units": m.units, "mixed": m.mixed,
        "order_id": m.order_id, "jiyun_id": m.jiyun_id, "jiyun_no": m.jiyun_no,
        "weight_kg": _num(m.weight_kg), "length_cm": _num(m.length_cm), "width_cm": _num(m.width_cm), "height_cm": _num(m.height_cm),
        "source": m.source, "source_label": SOURCES.get(m.source, m.source),
        "measured_at": m.measured_at.isoformat() if m.measured_at else None, "memo": m.memo,
    }


async def _is_mixed(j: Optional[JiyunShipment], order_id: int) -> bool:
    """같은 집운 번호(-2/-3 뗀 것) 또는 같은 집운 묶음에 다른 주문이 있으면 한 상자에 여러 주문 = 합포장."""
    if not j:
        return False
    others = JiyunShipment.filter(deleted_at=None).exclude(order_id=order_id)
    if j.bundle_id and await others.filter(bundle_id=j.bundle_id).exists():
        return True
    base = _base_no(j.jiyun_no)
    if base and await others.filter(jiyun_no__startswith=base).exists():
        for s in await others.filter(jiyun_no__startswith=base).values_list("jiyun_no", flat=True):
            if _base_no(s) == base:
                return True
    return False


async def _resolve(order: MarketOrder) -> dict:
    code, option_id, bundle = parse_sku(order.seller_code)
    product = await Product.get_or_none(code=code) if code else None
    units = max(1, bundle) * max(1, order.quantity or 1)
    # 주문 1건을 집운 여러 건(번호 다름)으로 나눠 보냈으면 상자 하나에는 그만큼 나눈 개수만 든다 (2026-11-26 정정 — 수량 2 주문이 6.6kg 상자 2개로 간 사례)
    nos = {_base_no(n) for n in await JiyunShipment.filter(deleted_at=None, order_id=order.id).values_list("jiyun_no", flat=True) if n}
    if len(nos) > 1 and units % len(nos) == 0:
        units //= len(nos)
    return {"product_id": product.id if product else None, "option_id": option_id, "sku": (order.seller_code or "").strip() or None,
            "units": units}


class MeasureService:
    @staticmethod
    async def record(*, order_id: Optional[int] = None, order_code: Optional[str] = None, jiyun_no: Optional[str] = None,
                     weight_kg=None, length_cm=None, width_cm=None, height_cm=None, source: str = "jiyun",
                     mixed: Optional[bool] = None, memo: Optional[str] = None, user_id: Optional[int] = None) -> dict:
        """주문 1건의 상자 실측을 넣는다. 같은 주문 × 같은 집운 번호가 이미 있으면 그 줄을 고친다 (보낸 값만)."""
        if source not in SOURCES:
            raise HTTPException(status_code=400, detail="source 는 jiyun · manual · backfill 중 하나입니다.")
        j = None
        if jiyun_no:
            j = await JiyunShipment.filter(deleted_at=None, jiyun_no=jiyun_no.strip()).first()
        order = None
        if order_id:
            order = await MarketOrder.get_or_none(id=order_id)
        elif order_code:
            order = await MarketOrder.filter(code=order_code.strip()).first()
        elif j:
            order = await MarketOrder.get_or_none(id=j.order_id)
        if not order:
            raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다.")
        if not j:
            j = await JiyunShipment.filter(deleted_at=None, order_id=order.id).order_by("-id").first()
        r = await _resolve(order)
        auto_mixed = await _is_mixed(j, order.id)
        no = (jiyun_no or (j.jiyun_no if j else None) or None)
        row = await alive().filter(order_id=order.id, jiyun_no=no).first() if no else await alive().filter(order_id=order.id).first()
        vals = {k: Decimal(str(v)) for k, v in
                {"weight_kg": weight_kg, "length_cm": length_cm, "width_cm": width_cm, "height_cm": height_cm}.items() if v is not None}
        if any(v <= 0 for v in vals.values()):
            raise HTTPException(status_code=400, detail="무게·크기는 0보다 커야 합니다.")
        now = datetime.now(timezone.utc)
        if row:
            for k, v in vals.items():
                setattr(row, k, v)
            row.mixed = mixed if mixed is not None else (row.mixed or auto_mixed)
            row.source, row.measured_at = source, now
            if memo is not None:
                row.memo = memo
            row.product_id, row.option_id, row.sku, row.units = r["product_id"], r["option_id"], r["sku"], r["units"]
            row.jiyun_id = j.id if j else row.jiyun_id
            await row.save()
        else:
            row = await OptionMeasure.create(**r, **vals, order_id=order.id, jiyun_id=j.id if j else None, jiyun_no=no,
                                             mixed=mixed if mixed is not None else auto_mixed, source=source,
                                             measured_at=now, memo=memo, created_by_id=user_id)
        return measure_dict(row)

    @staticmethod
    async def list(product_id: Optional[int] = None, option_id: Optional[int] = None, order_id: Optional[int] = None,
                   limit: int = 200) -> list[dict]:
        q = alive()
        if product_id:
            q = q.filter(product_id=product_id)
        if option_id:
            q = q.filter(option_id=option_id)
        if order_id:
            q = q.filter(order_id=order_id)
        return [measure_dict(m) for m in await q.order_by("-id").limit(min(max(limit, 1), 1000))]

    @staticmethod
    async def delete(measure_id: int) -> None:
        m = await alive().get_or_none(id=measure_id)
        if not m:
            raise HTTPException(status_code=404, detail="실측 기록이 없습니다.")
        m.deleted_at = datetime.now(timezone.utc)
        await m.save()

    @staticmethod
    async def backfill(dry: bool = True) -> dict:
        """무게가 있는 예전 집운 기록 → backfill 실측 (무게만). 합포장 · SKU 못 읽음 · 이미 있음은 건너뛴다."""
        made, skipped = [], {"exists": 0, "mixed": 0, "no_option": 0}
        for j in await JiyunShipment.filter(deleted_at=None, weight_kg__not_isnull=True).order_by("id"):
            if await alive().filter(jiyun_id=j.id).exists():
                skipped["exists"] += 1
                continue
            order = await MarketOrder.get_or_none(id=j.order_id)
            if not order:
                continue
            r = await _resolve(order)
            if not r["option_id"]:
                skipped["no_option"] += 1
                continue
            mixed = await _is_mixed(j, order.id)
            if mixed:
                skipped["mixed"] += 1
            made.append({"jiyun_no": j.jiyun_no, "order": order.code, "sku": r["sku"], "units": r["units"],
                         "weight_kg": float(j.weight_kg), "mixed": mixed})
            if not dry:
                await OptionMeasure.create(**r, order_id=order.id, jiyun_id=j.id, jiyun_no=j.jiyun_no, weight_kg=j.weight_kg,
                                           mixed=mixed, source="backfill", measured_at=j.requested_at or j.created_at,
                                           memo="예전 집운 기록 요금 무게 (크기 없음)")
        return {"dry": dry, "count": len(made), "skipped": skipped, "rows": made}


async def measure_averages(option_ids: list[int]) -> dict[tuple[int, int], dict]:
    """(옵션 id, units) → 실측 평균. 합포장 · 무게 없는 줄은 뺀다. 크기는 세 변이 다 있는 줄만으로 평균."""
    if not option_ids:
        return {}
    acc: dict[tuple[int, int], dict] = {}
    for m in await alive().filter(option_id__in=option_ids, mixed=False, weight_kg__not_isnull=True):
        a = acc.setdefault((m.option_id, m.units), {"w": [], "dims": []})
        a["w"].append(float(m.weight_kg))
        if m.length_cm and m.width_cm and m.height_cm:
            a["dims"].append((float(m.length_cm), float(m.width_cm), float(m.height_cm)))
    out = {}
    for k, a in acc.items():
        d = a["dims"]
        out[k] = {"count": len(a["w"]), "weight_kg": round(sum(a["w"]) / len(a["w"]), 3),
                  "dims_count": len(d),
                  "length_cm": round(sum(x[0] for x in d) / len(d), 1) if d else None,
                  "width_cm": round(sum(x[1] for x in d) / len(d), 1) if d else None,
                  "height_cm": round(sum(x[2] for x in d) / len(d), 1) if d else None}
    return out
