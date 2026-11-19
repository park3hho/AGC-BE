"""구매 소포 — 판매처가 한 구매를 여러 소포로 나눠 보낸 경우 (2026-11-19).

규칙: 소포가 하나라도 기록돼 있으면 구매의 창고 입고(cn_status=arrived)는
'기록된 소포 전부 입고 + 입고 수 ≥ package_count' 일 때만. 일부만 입고면 cn_status 는 shipped 로 둔다
→ 묶음 ready(집운 결제 안내)가 첫 소포만으로 켜지지 않는다 (11-19 OR-261117-0001 2박스 사고)."""

from datetime import datetime, timezone

from fastapi import HTTPException

from core.purchase_config import PACKAGE_STATUS
from models.order.order import MarketOrder
from models.order.purchase import PurchasePackage, TaobaoPurchase
from services.order.order_service import actor_of, log_event, restage


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def package_dict(k: PurchasePackage) -> dict:
    return {"id": k.id, "purchase_id": k.purchase_id, "courier": k.courier, "tracking_no": k.tracking_no,
            "status": k.status, "status_label": PACKAGE_STATUS.get(k.status, k.status),
            "shipped_at": _iso(k.shipped_at), "arrived_at": _iso(k.arrived_at), "last_text": k.last_text,
            "memo": k.memo, "created_at": _iso(k.created_at), "updated_at": _iso(k.updated_at)}


async def gate(p: TaobaoPurchase, package_count: int | None = None) -> dict:
    """소포 입고 현황 — {packages, arrived, need, complete}.
    소포 기록이 없으면: package_count 가 2 이상이면 complete=False(덜 기록됨), 아니면 None(구매 상태만으로 판단)."""
    pk = await PurchasePackage.filter(purchase_id=p.id).order_by("id")
    cnt = package_count if package_count is not None else p.package_count
    if not pk:
        return {"packages": 0, "arrived": 0, "need": cnt or 0, "complete": None if not cnt or cnt <= 1 else False}
    arrived = sum(1 for k in pk if k.status == "arrived")
    need = max(len(pk), cnt or 0)
    return {"packages": len(pk), "arrived": arrived, "need": need, "complete": arrived >= need}


async def _recompute(p: TaobaoPurchase, actor) -> None:
    """소포 상태로 구매의 cn_status · 시각을 맞춘다 (취소·문제 상태는 건드리지 않음)."""
    if p.cn_status in ("cancelled", "problem"):
        return
    pk = await PurchasePackage.filter(purchase_id=p.id).order_by("id")
    if not pk:
        return
    g = await gate(p)
    before = (p.cn_status, p.arrived_at, p.shipped_at, p.cn_tracking_no)
    ships = [k.shipped_at for k in pk if k.shipped_at]
    if g["complete"]:
        p.cn_status = "arrived"
        p.arrived_at = max([k.arrived_at for k in pk if k.arrived_at] or [p.arrived_at or datetime.now(timezone.utc)])
    else:
        p.cn_status = "shipped"
        p.arrived_at = None
    if ships and not p.shipped_at:
        p.shipped_at = min(ships)
    if not p.cn_tracking_no:
        p.cn_tracking_no, p.cn_courier = pk[0].tracking_no, p.cn_courier or pk[0].courier
    if before != (p.cn_status, p.arrived_at, p.shipped_at, p.cn_tracking_no):
        p.status_source = "manual"
        await p.save()
        order = await MarketOrder.get(id=p.order_id)
        await log_event(order, actor, "purchase_changed",
                        f"타오바오 {p.taobao_order_no} — 소포 {g['arrived']}/{g['need']} 입고 → {p.cn_status}",
                        {"purchase_id": p.id, "packages": g})
        await restage(order, actor, "소포 입고 상태 변경")
        try:
            from services.order.bundle_service import recompute_for_order
            await recompute_for_order(p.order_id)
        except Exception:   # 묶음 재계산 실패는 다음 주기에 sync_all 이 맞춘다
            pass


async def _purchase(purchase_id: int) -> TaobaoPurchase:
    p = await TaobaoPurchase.get_or_none(id=purchase_id, deleted_at=None)
    if not p:
        raise HTTPException(status_code=404, detail="타오바오 구매를 찾지 못했습니다.")
    return p


def _check_status(v):
    if v is not None and v not in PACKAGE_STATUS:
        raise HTTPException(status_code=400, detail="소포 상태는 shipped · arrived · problem 중 하나예요.")


async def list_packages(purchase_id: int) -> dict:
    p = await _purchase(purchase_id)
    pk = await PurchasePackage.filter(purchase_id=p.id).order_by("id")
    return {"items": [package_dict(k) for k in pk], "gate": await gate(p)}


async def add(purchase_id: int, data: dict, auth: dict) -> dict:
    p = await _purchase(purchase_id)
    _check_status(data.get("status"))
    if await PurchasePackage.filter(purchase_id=p.id, tracking_no=data["tracking_no"]).exists():
        raise HTTPException(status_code=409, detail="이미 기록된 운송장이에요.")
    # 첫 추가 소포면, 구매에 이미 적힌 운송장도 소포 1 로 같이 남긴다
    if p.cn_tracking_no and p.cn_tracking_no != data["tracking_no"] and \
            not await PurchasePackage.filter(purchase_id=p.id).exists():
        await PurchasePackage.create(purchase_id=p.id, tracking_no=p.cn_tracking_no, courier=p.cn_courier,
                                     status="arrived" if p.cn_status == "arrived" else "shipped",
                                     shipped_at=p.shipped_at, arrived_at=p.arrived_at)
    if data.get("status") == "arrived" and not data.get("arrived_at"):
        data["arrived_at"] = datetime.now(timezone.utc)
    k = await PurchasePackage.create(purchase_id=p.id, **data)
    await _recompute(p, actor_of(auth))
    return {"item": package_dict(k), "gate": await gate(p)}


async def patch(package_id: int, data: dict, auth: dict) -> dict:
    k = await PurchasePackage.get_or_none(id=package_id)
    if not k:
        raise HTTPException(status_code=404, detail="소포를 찾지 못했어요.")
    _check_status(data.get("status"))
    if not data:
        raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
    if data.get("status") == "arrived" and not data.get("arrived_at") and not k.arrived_at:
        data["arrived_at"] = datetime.now(timezone.utc)
    await k.update_from_dict(data).save()
    p = await _purchase(k.purchase_id)
    await _recompute(p, actor_of(auth))
    return {"item": package_dict(k), "gate": await gate(p)}


async def delete(package_id: int, auth: dict) -> dict:
    k = await PurchasePackage.get_or_none(id=package_id)
    if not k:
        raise HTTPException(status_code=404, detail="소포를 찾지 못했어요.")
    pid = k.purchase_id
    await k.delete()
    p = await _purchase(pid)
    await _recompute(p, actor_of(auth))
    return {"gate": await gate(p)}
