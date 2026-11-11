"""수입식품 구매대행 수입신고 기록 (2026-11-11).

신고서 1장 = ImportDeclaration 1건, 같은 B/L 로 온 같은 고객 주문들을 orders 로 묶는다.
추가·수정·삭제마다 묶인 주문마다 OrderEvent 한 줄 (import_decl_created · import_decl_changed · import_decl_deleted).
pending(): 집운이 출고돼 B/L 이 있고 통관 전인데 신고서가 없는 B/L — 30분 점검이 이걸 보고 유니패스에 낸다."""

from datetime import date, datetime, timezone

from fastapi import HTTPException

from core.import_decl_config import DECL_DEFAULTS, DECL_KIND, DECL_STATUS, DECL_TRACKED
from models.order.import_decl import ImportDeclaration
from models.order.jiyun import JiyunShipment
from models.order.order import MarketOrder
from models.order.purchase import TaobaoPurchase
from services.order.order_service import actor_of, log_event
from services.order.pccc import mask_name


def alive():
    return ImportDeclaration.filter(deleted_at=None)


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


async def decl_dict(d: ImportDeclaration) -> dict:
    await d.fetch_related("orders")
    return {
        "id": d.id, "decl_no": d.decl_no, "receipt_no": d.receipt_no,
        "kind": d.kind, "kind_label": DECL_KIND.get(d.kind, d.kind),
        "status": d.status, "status_label": DECL_STATUS.get(d.status, d.status),
        "agency_code": d.agency_code, "bl_no": d.bl_no, "vessel": d.vessel,
        "arrival_date": _plain(d.arrival_date), "warehouse_code": d.warehouse_code, "consignee": d.consignee,
        "items": d.items or [], "seller_site": d.seller_site, "shipper_site": d.shipper_site,
        "sent_at": _plain(d.sent_at), "accepted_at": _plain(d.accepted_at), "approved_at": _plain(d.approved_at),
        "result": d.result, "memo": d.memo,
        "orders": [{"id": o.id, "code": o.code, "market": o.market, "product_name": o.product_name,
                    "option_name": o.option_name, "quantity": o.quantity} for o in sorted(d.orders, key=lambda x: x.id)],
        "created_at": d.created_at.isoformat(), "updated_at": d.updated_at.isoformat(),
    }


def _snap(d: ImportDeclaration) -> dict:
    return {k: _plain(getattr(d, k)) for k in DECL_TRACKED}


async def _orders(ids: list[int]) -> list[MarketOrder]:
    rows = await MarketOrder.filter(id__in=ids)
    if len(rows) != len(set(ids)):
        raise HTTPException(status_code=404, detail="고객 주문을 찾지 못했습니다.")
    names = {(r.receiver_name or "").replace(" ", "") for r in rows}
    if len(names) > 1:
        raise HTTPException(status_code=409, detail="받는 사람이 다른 주문은 신고서를 따로 내야 해요 (받는 사람 1명 단위).")
    return rows


def _log_text(d: ImportDeclaration, what: str) -> str:
    no = d.decl_no or "신청번호 없음"
    return f"수입신고 {no} {what} — {DECL_STATUS.get(d.status, d.status)}" + (f" · B/L {d.bl_no}" if d.bl_no else "")


class ImportDeclService:
    @staticmethod
    async def list(order_id: int | None, status: str | None, q: str | None, limit: int) -> list[dict]:
        qs = alive()
        if order_id:
            qs = qs.filter(orders__id=order_id)
        if status:
            qs = qs.filter(status=status)
        if q:
            q = q.strip()
            from tortoise.expressions import Q
            qs = qs.filter(Q(decl_no__icontains=q) | Q(bl_no__icontains=q) | Q(orders__code__icontains=q))
        rows = await qs.distinct().order_by("-id").limit(limit)
        return [await decl_dict(d) for d in rows]

    @staticmethod
    async def get(decl_id: int) -> dict:
        d = await alive().get_or_none(id=decl_id)
        if not d:
            raise HTTPException(status_code=404, detail="수입신고 기록을 찾지 못했습니다.")
        return await decl_dict(d)

    @staticmethod
    async def create(body, auth: dict) -> dict:
        orders = await _orders(body.order_ids)
        data = body.model_dump(exclude={"order_ids"}, exclude_none=True)
        for k, v in DECL_DEFAULTS.items():
            data.setdefault(k, v)
        if not data.get("consignee"):
            data["consignee"] = mask_name(orders[0].receiver_name or "")
        if data.get("status") in ("sent", "accepted", "approved") and not data.get("sent_at"):
            data["sent_at"] = datetime.now(timezone.utc)
        if data.get("decl_no") and await alive().filter(decl_no=data["decl_no"]).exists():
            raise HTTPException(status_code=409, detail=f"신청번호 {data['decl_no']} 는 이미 기록돼 있어요.")
        d = await ImportDeclaration.create(**data, created_by_id=auth.get("user_id"))
        await d.orders.add(*orders)
        actor = actor_of(auth)
        for o in orders:
            await log_event(o, actor, "import_decl_created", _log_text(d, "기록"),
                            {"import_decl_id": d.id, "step": "통관", "stage": "process", "source": "import_decl",
                             "values": {k: v for k, v in _snap(d).items() if v not in (None, [], "")}})
        return await decl_dict(d)

    @staticmethod
    async def update(decl_id: int, body, auth: dict) -> dict:
        d = await alive().get_or_none(id=decl_id)
        if not d:
            raise HTTPException(status_code=404, detail="수입신고 기록을 찾지 못했습니다.")
        data = body.model_dump(exclude_unset=True)
        order_ids = data.pop("order_ids", None)
        if not data and order_ids is None:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        if data.get("decl_no") and await alive().filter(decl_no=data["decl_no"]).exclude(id=d.id).exists():
            raise HTTPException(status_code=409, detail=f"신청번호 {data['decl_no']} 는 이미 기록돼 있어요.")
        now = datetime.now(timezone.utc)
        st = data.get("status")
        if st in ("sent", "accepted", "approved") and not (data.get("sent_at") or d.sent_at):
            data["sent_at"] = now
        if st == "accepted" and not (data.get("accepted_at") or d.accepted_at):
            data["accepted_at"] = now
        if st == "approved" and not (data.get("approved_at") or d.approved_at):
            data["approved_at"] = now
        before = _snap(d)
        await d.update_from_dict(data).save()
        if order_ids is not None:
            orders = await _orders(order_ids)
            await d.orders.clear()
            await d.orders.add(*orders)
        after = _snap(d)
        changes = {k: {"from": before[k], "to": after[k]} for k in DECL_TRACKED if before[k] != after[k]}
        await d.fetch_related("orders")
        if changes or order_ids is not None:
            actor = actor_of(auth)
            for o in d.orders:
                await log_event(o, actor, "import_decl_changed", _log_text(d, "수정"),
                                {"import_decl_id": d.id, "step": "통관", "stage": "process", "source": "import_decl",
                                 "changes": changes})
        return await decl_dict(d)

    @staticmethod
    async def delete(decl_id: int, auth: dict) -> None:
        d = await alive().get_or_none(id=decl_id)
        if not d:
            raise HTTPException(status_code=404, detail="수입신고 기록을 찾지 못했습니다.")
        d.deleted_at = datetime.now(timezone.utc)
        await d.save(update_fields=["deleted_at", "updated_at"])
        await d.fetch_related("orders")
        for o in d.orders:
            await log_event(o, actor_of(auth), "import_decl_deleted", _log_text(d, "기록 삭제"),
                            {"import_decl_id": d.id, "values": _snap(d)})

    @staticmethod
    async def pending() -> list[dict]:
        """신고해야 할 B/L — 집운 출고 · B/L 있음 · 통관 전 · 신고서(반려 빼고) 없음. B/L 하나에 주문 여러 건(묶음)."""
        js = await JiyunShipment.filter(deleted_at=None, status="dispatched", hbl__isnull=False,
                                        customs_cleared_at__isnull=True).prefetch_related("order").order_by("id")
        by: dict[str, dict] = {}
        for j in js:
            o = j.order
            if not j.hbl or o.is_test or o.stage == "cancelled" and not j.hbl:
                continue
            g = by.setdefault(j.hbl, {"bl_no": j.hbl, "jiyun_ids": [], "orders": {}, "dispatched_at": _plain(j.dispatched_at),
                                      "customs_status": j.customs_status})
            g["jiyun_ids"].append(j.id)
            g["orders"][o.id] = o
        if not by:
            return []
        ids = [oid for g in by.values() for oid in g["orders"]]
        handled = set(await ImportDeclaration.filter(deleted_at=None, bl_no__in=list(by)).exclude(status="rejected")
                      .values_list("bl_no", flat=True))   # B/L 마다 (성남처럼 한 고객이 B/L 두 개일 수 있음)
        urls: dict[int, list] = {}
        for p in await TaobaoPurchase.filter(order_id__in=ids, deleted_at=None).exclude(cn_status="cancelled"):
            if p.item_url:
                urls.setdefault(p.order_id, []).append(p.item_url)
        out = []
        for g in by.values():
            orders = sorted(g["orders"].values(), key=lambda x: x.id)
            if g["bl_no"] in handled:
                continue
            out.append({
                "bl_no": g["bl_no"], "jiyun_ids": g["jiyun_ids"], "dispatched_at": g["dispatched_at"],
                "customs_status": g["customs_status"], "consignee": mask_name(orders[0].receiver_name or ""),
                "orders": [{"id": o.id, "code": o.code, "market": o.market, "stage": o.stage,
                            "product_name": o.product_name, "option_name": o.option_name, "quantity": o.quantity,
                            "taobao_urls": urls.get(o.id, [])} for o in orders],
            })
        return out
