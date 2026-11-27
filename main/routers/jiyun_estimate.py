import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from models.order.order import MarketOrder
from services.pricing import jiyun_estimate as je

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jiyun-estimate", tags=["JiyunEstimate"])

# 집운 운임 예측 (2026-11-26) — services/pricing/jiyun_estimate.py. 비공개(원가·운임 구조).


class Item(BaseModel):
    option_id: int
    units: int = Field(default=1, ge=1, le=100)


class EstimateBody(BaseModel):
    items: list[Item] = Field(default_factory=list)       # 지금 한 집운으로 갈 것
    add: list[Item] = Field(default_factory=list)         # 더 담으면? (비우면 items 만 계산)


def _t(xs: list[Item]) -> list[tuple[int, int]]:
    return [(x.option_id, x.units) for x in xs]


@router.post("")
async def estimate(body: EstimateBody, auth=Depends(require_feature(Feature.ORDER))):
    ctx = await je.load_context()
    if body.add:
        return success(result=je.marginal(ctx, _t(body.items), _t(body.add)))
    if not body.items:
        raise HTTPException(status_code=400, detail="items 가 비었어요.")
    return success(result=je.estimate(ctx, _t(body.items)), packing=je.pack(ctx, _t(body.items)))


def _od(o: MarketOrder) -> dict:
    return {"id": o.id, "seller_code": o.seller_code, "quantity": o.quantity}


@router.get("/order/{order_id}")
async def for_order(order_id: int, auth=Depends(require_feature(Feature.ORDER))):
    """주문 1건의 예상 집운비 + 같은 고객 묶음(jiyun_bundle)이 있으면 묶음 전체·이 주문을 더할 때 늘어나는 운임."""
    o = await MarketOrder.get_or_none(id=order_id)
    if not o:
        raise HTTPException(status_code=404, detail="주문이 없어요.")
    ctx = await je.load_context()
    mine = je.items_from_orders([_od(o)])
    if not mine:
        raise HTTPException(status_code=400, detail="판매자 상품코드에서 옵션을 못 읽었어요.")
    out: dict = {"order": je.estimate(ctx, mine), "bundle": None}
    if o.jiyun_bundle_id:
        others = await MarketOrder.filter(jiyun_bundle_id=o.jiyun_bundle_id).exclude(id=o.id)
        if others:
            cur = je.items_from_orders([_od(x) for x in others])
            m = je.marginal(ctx, cur, mine)
            out["bundle"] = {"orders": [x.code for x in others], **m,
                             "saving_cny": round(m["alone_cny"] - m["added_cny"], 2)}   # 따로 보낼 때보다 아끼는 운임
    return success(**out)
