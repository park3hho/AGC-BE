"""가격 책정 › 자사몰 판매 — 자사몰 판매가 계산 (계산 · 표시만, 2026-11-27)."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from services.pricing.shop_calc import apply, calc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shop-pricing", tags=["ShopPricing"])


@router.get("")
async def shop_pricing(auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(**await calc())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"자사몰 판매가 계산 실패: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ── 자사몰 장바구니 운임 (2026-11-27) — SHOP BE 가 서버끼리 부른다 (API 키, research 권한) ──
from pydantic import BaseModel, Field   # noqa: E402

from services.pricing import jiyun_estimate as je   # noqa: E402
from services.pricing.exchange_rate_service import ExchangeRateService   # noqa: E402


class FreightItem(BaseModel):
    option_id: int
    units: int = Field(default=1, ge=1, le=100)     # 기본 단위 개수 (sku 묶음 × 수량)


class FreightBody(BaseModel):
    items: list[FreightItem] = Field(min_length=1, max_length=50)


@router.post("/freight")
async def freight(body: FreightBody, auth=Depends(require_feature(Feature.RESEARCH))):
    """장바구니 전체 → 가장 싼 상자 구성(je.pack)의 운임. 원화 = 위안 × 현재 환율, 원 단위 반올림.
    응답에는 고객에게 보여 줄 값만 (상자별 무게 · 운임 원화, 총 무게). 원가 · 요율 구조는 내보내지 않는다."""
    try:
        ctx = await je.load_context()
        p = je.pack(ctx, [(x.option_id, x.units) for x in body.items])
        fx = float(await ExchangeRateService.current_rate())
        boxes = [{"weight_g": b["weight_g"], "billable_kg": b["billable_kg"], "fee_krw": round(b["fee_cny"] * fx)}
                 for b in p["boxes"]]
        return success(fee_krw=sum(b["fee_krw"] for b in boxes), weight_g=p["weight_g"], boxes=boxes,
                       parts=p["parts"], units=sum(x.units for x in body.items))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"자사몰 운임 계산 실패: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.post("/apply")
async def apply_prices(auth=Depends(require_feature(Feature.RESEARCH))):
    """자사몰 판매가 저장 — 배송비 별도 가격 (shop_sale_price). 매일 환율 갱신 뒤에도 자동으로 돈다."""
    try:
        return success(**await apply())
    except Exception as e:
        logger.exception("자사몰 판매가 저장 실패")
        raise HTTPException(status_code=500, detail=f"자사몰 판매가 저장 실패: {type(e).__name__}")

@router.post("/cost-backfill")
async def cost_backfill(auth=Depends(require_feature(Feature.RESEARCH))):
    """매입가 = 최근 실구매 1단위가 — 지금까지 구매 기록으로 한 번 적용 (2026-11-27). 바뀐 옵션 · 제외 건수."""
    from services.order.cost_sync import backfill
    try:
        d = await backfill()
        d["changed"] = [{**c, "old": str(c["old"]) if c["old"] is not None else None, "new": str(c["new"])} for c in d["changed"]]
        return success(**d)
    except Exception as e:
        logger.exception("매입가 백필 실패")
        raise HTTPException(status_code=500, detail=f"매입가 백필 실패: {type(e).__name__}")
