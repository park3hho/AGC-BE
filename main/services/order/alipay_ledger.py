"""알리페이(즈푸바오) 잔액 장부 — 충전한 위안의 환율로 선입선출 원화 계산 (2026-11-20 사용자).

- 충전(AlipayTopup): 위안 · 낸 원화 → 환율 = 원화 ÷ 위안.
- 결제(AlipaySpend): 타오바오 구매 · 집운 운임 중 '알리페이 잔액' 결제를 자동으로 가져온다(pay_method alipay + charged_source 에 '잔액').
  오래된 충전부터 깎고, 두 충전에 걸치면 깎은 위안 비율대로 원화를 더한다 (예: ¥40×202 + ¥23×201).
- 계산한 원화는 그 구매 · 집운 기록의 charged_krw · charged_source 에 넣고 FIN 지출도 다시 보낸다.
- 장부 시작 = 기초 잔액(is_opening) 시각. 그 전 결제는 건드리지 않는다(예전 1위안 202원 규칙 그대로).
- 결제 시각 전에 들어온 충전만 쓴다. 모자라면 short_cny 로 표시하고 마지막 충전 환율(없으면 202)로 임시 계산."""

import asyncio
import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException

from models.order.alipay import AlipaySpend, AlipayTopup
from models.order.jiyun import JiyunShipment
from models.order.purchase import TaobaoPurchase

logger = logging.getLogger(__name__)
FALLBACK_RATE = Decimal("202")
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
_lock = asyncio.Lock()


def _rate(t: AlipayTopup) -> Decimal:
    return (Decimal(t.krw) / Decimal(t.cny)).quantize(Q4, ROUND_HALF_UP) if t.cny else FALLBACK_RATE


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _won(v: Decimal) -> int:
    return int(v.quantize(Decimal("1"), ROUND_HALF_UP))


def topup_dict(t: AlipayTopup, left: Decimal | None = None) -> dict:
    return {"id": t.id, "topped_at": _iso(t.topped_at), "cny": f"{t.cny:.2f}", "krw": t.krw, "rate": f"{_rate(t):.4f}",
            "is_opening": t.is_opening, "memo": t.memo, "left_cny": f"{left:.2f}" if left is not None else None}


def spend_dict(s: AlipaySpend) -> dict:
    return {"id": s.id, "spent_at": _iso(s.spent_at), "cny": f"{s.cny:.2f}", "kind": s.kind, "ref_id": s.ref_id, "krw": s.krw,
            "rate": f"{(Decimal(s.krw) / s.cny):.4f}" if s.krw and s.cny else None,
            "allocations": s.allocations or [], "short_cny": f"{s.short_cny:.2f}", "memo": s.memo}


def _source_text(allocs: list[dict], short: Decimal) -> str:
    parts = [f"¥{Decimal(a['cny']):g}×{Decimal(a['rate']):.2f}" for a in allocs]
    txt = "알리페이 잔액 선입선출 " + " + ".join(parts)
    if short > 0:
        txt += f" (충전 기록 부족 ¥{short:g})"
    return txt if len(txt) <= 100 else txt[:97] + "…"


async def _start() -> datetime | None:
    o = await AlipayTopup.filter(deleted_at=None, is_opening=True).order_by("topped_at").first()
    if o:
        return o.topped_at
    f = await AlipayTopup.filter(deleted_at=None).order_by("topped_at").first()
    return f.topped_at if f else None


async def _sync_refs(start: datetime) -> None:
    """구매 · 집운 기록의 잔액 결제를 결제 기록으로 맞춘다 (새로 생김 · 금액 바뀜 · 빠짐)."""
    want: dict[tuple[str, int], tuple[datetime, Decimal]] = {}
    for p in await TaobaoPurchase.filter(deleted_at=None, pay_method="alipay", purchased_at__gte=start, charged_source__icontains="잔액"):
        cny = p.pay_amount if (p.pay_currency or "CNY") == "CNY" and p.pay_amount is not None else p.paid_cny
        if cny and cny > 0 and p.cn_status != "cancelled":
            want[("purchase", p.id)] = (p.purchased_at, Decimal(cny).quantize(Q2))
    for j in await JiyunShipment.filter(deleted_at=None, pay_method="alipay", requested_at__gte=start, charged_source__icontains="잔액").exclude(status="cancelled"):
        cny = j.pay_amount if (j.pay_currency or "CNY") == "CNY" and j.pay_amount is not None else j.fee_cny
        if cny and cny > 0:
            want[("jiyun", j.id)] = (j.requested_at, Decimal(cny).quantize(Q2))
    have = {(s.kind, s.ref_id): s for s in await AlipaySpend.filter(deleted_at=None, kind__in=["purchase", "jiyun"])}
    now = datetime.now(timezone.utc)
    for k, (at, cny) in want.items():
        s = have.get(k)
        if not s:
            await AlipaySpend.create(kind=k[0], ref_id=k[1], spent_at=at, cny=cny)
        elif s.cny != cny or s.spent_at != at:
            s.cny, s.spent_at = cny, at
            await s.save(update_fields=["cny", "spent_at", "updated_at"])
    for k, s in have.items():
        if k not in want:
            s.deleted_at = now
            await s.save(update_fields=["deleted_at", "updated_at"])


async def recompute(apply: bool = True) -> dict:
    """선입선출 다시 계산 → 결제마다 원화, (apply) 구매 · 집운 기록에 반영."""
    async with _lock:
        start = await _start()
        if not start:
            return {"lots": [], "spends": 0, "changed": 0, "note": "충전 기록 없음"}
        await _sync_refs(start)
        tops = await AlipayTopup.filter(deleted_at=None).order_by("topped_at", "id")
        left = {t.id: Decimal(t.cny) for t in tops}
        rates = {t.id: _rate(t) for t in tops}
        changed = 0
        touched: list[AlipaySpend] = []
        for s in await AlipaySpend.filter(deleted_at=None, spent_at__gte=start).order_by("spent_at", "id"):
            need = Decimal(s.cny)
            allocs, total = [], Decimal("0")
            last_rate = None
            for t in tops:
                if t.topped_at > s.spent_at:
                    break
                last_rate = rates[t.id]
                if need <= 0:
                    break
                if left[t.id] <= 0:
                    continue
                take = min(left[t.id], need)
                left[t.id] -= take
                need -= take
                won = take * rates[t.id]
                total += won
                allocs.append({"topup_id": t.id, "cny": f"{take:.2f}", "rate": f"{rates[t.id]:.4f}", "krw": f"{won:.2f}"})
            short = need if need > 0 else Decimal("0")
            if short:
                total += short * (last_rate or FALLBACK_RATE)
            krw = _won(total)
            if s.krw != krw or (s.allocations or []) != allocs or Decimal(s.short_cny or 0) != short:
                s.krw, s.allocations, s.short_cny = krw, allocs, short
                await s.save(update_fields=["krw", "allocations", "short_cny", "updated_at"])
                changed += 1
            touched.append(s)
        applied = 0
        if apply:
            for s in touched:
                if s.kind not in ("purchase", "jiyun") or s.ref_id is None:
                    continue
                M = TaobaoPurchase if s.kind == "purchase" else JiyunShipment
                rec = await M.get_or_none(id=s.ref_id)
                if not rec:
                    continue
                src = _source_text(s.allocations or [], Decimal(s.short_cny or 0))
                if rec.charged_krw != s.krw or rec.charged_source != src or rec.charged_status != "settled":
                    await M.filter(id=rec.id).update(charged_krw=s.krw, charged_source=src, charged_status="settled",
                                                     updated_at=datetime.now(timezone.utc))
                    applied += 1
            if applied:
                try:
                    from services.finance import fin_expense
                    fin_expense.kick()
                except Exception:
                    pass
        lots = [topup_dict(t, left[t.id]) for t in tops]
        balance = sum(left.values(), Decimal("0"))
        value = sum((left[t.id] * rates[t.id] for t in tops), Decimal("0"))
        return {"start": _iso(start), "balance_cny": f"{balance:.2f}", "balance_krw": _won(value),
                "avg_rate": f"{(value / balance):.4f}" if balance else None,
                "lots": lots, "spends": len(touched), "changed": changed, "applied": applied}


def kick() -> None:
    """구매 · 집운 저장 직후 — 기다리지 않고 뒤에서 다시 계산."""
    try:
        task = asyncio.get_running_loop().create_task(recompute(True))
        task.add_done_callback(lambda t: t.exception() and logger.warning(f"알리페이 장부 계산 오류: {t.exception()!r}"))
    except RuntimeError:
        pass


# ---------------------------------------------------------------- 화면 · API
async def ledger(limit: int = 200) -> dict:
    r = await recompute(True)
    spends = await AlipaySpend.filter(deleted_at=None).order_by("-spent_at", "-id").limit(limit)
    codes: dict[tuple[str, int], str] = {}
    pids = [s.ref_id for s in spends if s.kind == "purchase" and s.ref_id]
    jids = [s.ref_id for s in spends if s.kind == "jiyun" and s.ref_id]
    for p in await TaobaoPurchase.filter(id__in=pids).prefetch_related("order"):
        codes[("purchase", p.id)] = f"{p.order.code} 구매 {p.id}"
    for j in await JiyunShipment.filter(id__in=jids).prefetch_related("order"):
        codes[("jiyun", j.id)] = f"{j.order.code} 집운 {j.jiyun_no}"
    items = []
    for s in spends:
        d = spend_dict(s)
        d["label"] = codes.get((s.kind, s.ref_id)) or s.memo or s.kind
        items.append(d)
    return {**r, "items": items}


async def add_topup(data: dict) -> dict:
    if data.get("is_opening"):
        await AlipayTopup.filter(deleted_at=None, is_opening=True).update(is_opening=False)
    t = await AlipayTopup.create(**data)
    r = await recompute(True)
    return {"topup": topup_dict(t), "summary": {k: r[k] for k in ("balance_cny", "balance_krw", "avg_rate", "changed", "applied")}}


async def patch_topup(tid: int, data: dict) -> dict:
    t = await AlipayTopup.get_or_none(id=tid, deleted_at=None)
    if not t:
        raise HTTPException(status_code=404, detail="충전 기록을 찾지 못했어요.")
    if data.get("is_opening"):
        await AlipayTopup.filter(deleted_at=None, is_opening=True).exclude(id=tid).update(is_opening=False)
    await t.update_from_dict(data).save()
    await recompute(True)
    return {"topup": topup_dict(t)}


async def delete_topup(tid: int) -> None:
    t = await AlipayTopup.get_or_none(id=tid, deleted_at=None)
    if not t:
        raise HTTPException(status_code=404, detail="충전 기록을 찾지 못했어요.")
    t.deleted_at = datetime.now(timezone.utc)
    await t.save(update_fields=["deleted_at", "updated_at"])
    await recompute(True)


async def add_spend(data: dict) -> dict:
    """구매 · 집운 말고 잔액에서 나간 것 (예: 수수료 · 기타) — 직접 기록."""
    s = await AlipaySpend.create(kind="other", **data)
    await recompute(True)
    await s.refresh_from_db()
    return {"spend": spend_dict(s)}


async def delete_spend(sid: int) -> None:
    s = await AlipaySpend.get_or_none(id=sid, deleted_at=None, kind="other")
    if not s:
        raise HTTPException(status_code=404, detail="직접 기록한 결제만 지울 수 있어요 (구매·집운은 그 기록에서 고치세요).")
    s.deleted_at = datetime.now(timezone.utc)
    await s.save(update_fields=["deleted_at", "updated_at"])
    await recompute(True)
