import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from services.order.order_service import MARKETS, OrderService, collect_market, run_dict

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["Order"])

# 주문에는 개인정보(수취인·통관부호)가 있어 order 권한이 따로 있다. 응답에는 가린 값만 나간다.
# ⚠️ 이 파일의 로그에는 주문 원문·개인정보를 남기지 않는다.

Market = Literal["naver", "coupang", "shop"]


class CollectBody(BaseModel):
    markets: list[Market] = Field(default=list(MARKETS), min_length=1)
    since_hours: Optional[int] = Field(default=None, ge=1, le=24 * 31)   # 비우면 지난 수집 이후부터 (처음이면 3일)


def _fail(what: str, e: Exception):
    logger.error(f"주문 {what} 실패: {type(e).__name__}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_orders(
    stage: Optional[Literal["received", "processing", "done", "cancelled"]] = None,
    market: Optional[Market] = None,
    pccc: Optional[Literal["ok", "mismatch", "missing", "error", "pending"]] = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    q: Optional[str] = Query(default=None, max_length=60),   # 자사 코드(OR-…) · 마켓 주문번호 검색
    auth=Depends(require_feature(Feature.ORDER)),
):
    try:
        return success(**await OrderService.list(stage, market, pccc, page, size, q))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록 조회", e)


@router.post("/collect")
async def collect_orders(body: CollectBody, auth=Depends(require_feature(Feature.ORDER))):
    """마켓 주문을 지금 가져온다 — 새 주문·바뀐 주문은 통관부호를 바로 검증한다."""
    since = datetime.now(timezone.utc) - timedelta(hours=body.since_hours) if body.since_hours else None
    runs = []
    for m in dict.fromkeys(body.markets):
        try:
            runs.append(run_dict(await collect_market(m, auth, "manual", since)))
        except HTTPException:
            raise
        except Exception as e:
            raise _fail("수집", e)
    logger.info(f"주문 수집: by={auth['user_id']} " + " ".join(f"{r['market']}:+{r['created']}/~{r['changed']}/{r['ok']}" for r in runs))
    return success(runs=runs)


@router.get("/collect-status")
async def collect_status(auth=Depends(require_feature(Feature.ORDER))):
    """앱 아래 바용 — 마켓별 마지막 수집 1건 + 자동 수집 주기 (가볍게)."""
    try:
        return success(**await OrderService.collect_status())
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("수집 상태 조회", e)


@router.get("/updates")    # ★ /{order_id} 보다 먼저
async def order_updates(after: Optional[int] = Query(default=None, ge=0), auth=Depends(require_feature(Feature.ORDER))):
    """주문 접수 화면 알림 — after(이벤트 id) 뒤 새 주문·새 클레임. 화면은 자동 수집 주기마다 부른다."""
    try:
        return success(**await OrderService.updates(after))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("새 소식 조회", e)


@router.get("/sync-runs")
async def list_sync_runs(market: Optional[Market] = None, limit: int = Query(default=20, ge=1, le=100),
                         auth=Depends(require_feature(Feature.ORDER))):
    return success(items=await OrderService.runs(market, limit))


@router.get("/{order_id}")
async def get_order(order_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(**await OrderService.get(order_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("조회", e)


@router.post("/{order_id}/pccc-check")
async def recheck_pccc(order_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        data = await OrderService.recheck(order_id, auth)
        logger.info(f"통관부호 다시 검증: order_id={order_id} by={auth['user_id']} → {data['order']['pccc_status']}")
        return success(**data)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("통관부호 검증", e)


@router.post("/{order_id}/delivered")
async def mark_delivered(order_id: int, auth=Depends(require_feature(Feature.ORDER))):
    """자사몰 주문 배송 완료 표시 (국내 송장 있는 집운 기록이 있어야)."""
    try:
        data = await OrderService.mark_delivered(order_id, auth)
        logger.info(f"배송 완료 표시: order_id={order_id} by={auth['user_id']}")
        return success(**data)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("배송 완료 표시", e)


@router.post("/{order_id}/confirm")
async def confirm_order(order_id: int, auth=Depends(require_feature(Feature.ORDER))):
    """발주확인을 마켓에 보낸다 (쿠팡 상품준비중 · 네이버 발주 확인). 타오바오 구매 등록 전에 해야 한다."""
    try:
        data = await OrderService.confirm(order_id, auth)
        logger.info(f"발주확인: order_id={order_id} by={auth['user_id']} already={data.get('already', False)}")
        return success(**data)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("발주확인", e)
