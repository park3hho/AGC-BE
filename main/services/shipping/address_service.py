from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import ValidationError
from tortoise.transactions import in_transaction

from core.shipping_config import COURIERS, TRANSPORTS
from models.shipping.address import ShippingAddress
from schemas.shipping_address import ShippingAddressCreate, ShippingAddressUpdate

FIELDS = (
    "name", "country", "zip_code", "address", "address_detail", "phone", "uses", "defaults", "market_codes", "route",
    "memo",
)
NOT_NULL = {"name", "country", "address", "uses", "defaults", "market_codes"}


def courier_list() -> list[dict]:
    """고를 수 있는 국내 택배사 — FE 선택지 · 마켓별 코드 (진실의 원천은 core.shipping_config)."""
    return [{"key": k, "name": v["name"], "codes": v["codes"]} for k, v in COURIERS.items()]


def _route_out(route: dict | None) -> dict | None:
    """저장된 route + 택배사 이름 · 마켓별 택배사 코드(발송처리에 그대로 쓴다)."""
    if not route:
        return None
    c = COURIERS.get(route.get("courier") or "")
    return {
        **route,
        "transport_label": TRANSPORTS.get(route.get("transport"), route.get("transport")),
        "courier_name": c["name"] if c else None,
        "courier_codes": c["codes"] if c else {},
    }


def address_dict(a: ShippingAddress) -> dict:
    return {
        "id": a.id,
        **{f: getattr(a, f) for f in FIELDS},
        "route": _route_out(a.route),
        "overseas": a.country != "KR",
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }


def alive_addresses():
    return ShippingAddress.filter(deleted_at=None)


async def _get_alive(address_id: int) -> ShippingAddress:
    a = await alive_addresses().get_or_none(id=address_id)
    if not a:
        raise HTTPException(status_code=404, detail="주소를 찾지 못했습니다.")
    return a


def _dump(body: ShippingAddressCreate) -> dict:
    data = body.model_dump()
    data["market_codes"] = [dict(c) for c in data["market_codes"]]
    return data


async def _take_defaults(conn, keep_id: int, defaults: list[str]):
    """기본 용도는 용도마다 1곳만 — 이 주소가 기본이 되면 다른 주소에서 뺀다."""
    if not defaults:
        return
    for other in await alive_addresses().using_db(conn).exclude(id=keep_id):
        left = [d for d in (other.defaults or []) if d not in defaults]
        if left != (other.defaults or []):
            other.defaults = left
            await other.save(using_db=conn, update_fields=["defaults", "updated_at"])


class ShippingAddressService:
    @staticmethod
    async def list() -> list[dict]:
        rows = await alive_addresses().order_by("id")
        # 기본 출고지 → 기본 반품지 → 나머지
        rank = lambda a: (0 if "outbound" in (a.defaults or []) else 1 if a.defaults else 2, a.id)
        return [address_dict(a) for a in sorted(rows, key=rank)]

    @staticmethod
    async def get(address_id: int) -> dict:
        return address_dict(await _get_alive(address_id))

    @staticmethod
    async def create(body: ShippingAddressCreate, actor_id: int) -> dict:
        data = _dump(body)
        async with in_transaction() as conn:
            a = await ShippingAddress.create(**data, created_by_id=actor_id, using_db=conn)
            await _take_defaults(conn, a.id, data["defaults"])
        return address_dict(a)

    @staticmethod
    async def update(address_id: int, body: ShippingAddressUpdate) -> dict:
        changes = body.model_dump(exclude_unset=True)
        changes = {k: v for k, v in changes.items() if not (k in NOT_NULL and v is None)}
        if not changes:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        a = await _get_alive(address_id)
        merged = {f: getattr(a, f) for f in FIELDS} | changes
        # 용도를 줄이면 그 용도의 기본·마켓 코드도 같이 뺀다 (따로 안 보냈을 때만)
        uses = merged["uses"]
        if "defaults" not in changes:
            merged["defaults"] = [d for d in merged["defaults"] if d in uses]
        if "market_codes" not in changes:
            merged["market_codes"] = [c for c in merged["market_codes"] if c["use"] in uses]
        try:
            data = _dump(ShippingAddressCreate(**merged))
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors()[0]["msg"].removeprefix("Value error, "))
        async with in_transaction() as conn:
            for k, v in data.items():
                setattr(a, k, v)
            await a.save(using_db=conn)
            await _take_defaults(conn, a.id, data["defaults"])
        return address_dict(a)

    @staticmethod
    async def delete(address_id: int) -> None:
        a = await _get_alive(address_id)
        a.deleted_at = datetime.now(timezone.utc)
        a.defaults = []
        await a.save(update_fields=["deleted_at", "defaults", "updated_at"])
