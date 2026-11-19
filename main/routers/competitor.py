import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_auth, require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.competitor import CompetitorBulk, CompetitorUpsert, WatchUpsert
from services.product import competitor_queue
from services.product.competitor_service import CompetitorService, snapshots

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/competitor-prices", tags=["Competitor"])

# 마켓 최저가 경쟁 (2026-11-07) — 보기는 로그인만, 넣기·지우기는 research 권한 (에이전트 점검이 매일 덮어씀)


def _fail(what: str, e: Exception):
    logger.error(f"최저가 경쟁 {what} 실패: {type(e).__name__}: {e}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_competitors(platform: Optional[Literal["coupang", "naver"]] = None,
                           q: Optional[str] = Query(default=None, max_length=60), auth=Depends(require_auth)):
    try:
        return success(**await CompetitorService.list(platform, q))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록 조회", e)


@router.post("")
async def upsert_competitor(body: CompetitorUpsert, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        snaps = await snapshots({body.product_id})
        return success(item=await CompetitorService.upsert(body, snaps.get((body.product_id, body.platform, body.option_id))))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("저장", e)


@router.get("/queue")
async def competitor_queue_list(platform: Literal["coupang", "naver"], limit: int = Query(default=40, ge=1, le=500),
                                include_skipped: bool = False, auth=Depends(require_auth)):
    """확인 대기열 — 무엇을 먼저 볼지 서버가 정한다 (주문 → 바뀜 → 신규 → 검색 안 됨 → lose·match → 오래된 순, 2026-11-19).
    저장(POST /bulk)하면 그 줄의 사유가 저절로 풀린다."""
    try:
        return success(**await competitor_queue.queue(platform, limit, include_skipped))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("대기열 조회", e)


@router.get("/watch")
async def competitor_watch_list(platform: Optional[Literal["coupang", "naver"]] = None, auth=Depends(require_auth)):
    """점검 설정 (검색어 지정 · 검색 메모 · 사람 확인 · 보류 · 확인 필요 표시) 목록."""
    try:
        return success(items=await competitor_queue.watch_list(platform))
    except Exception as e:
        raise _fail("점검 설정 조회", e)


@router.put("/watch")
async def competitor_watch_upsert(body: WatchUpsert, auth=Depends(require_feature(Feature.RESEARCH))):
    """점검 설정 넣기 — 보낸 칸만 바꾼다. skip_days=N 은 오늘부터 N일 보류(0 = 해제), flag_reason 은 '확인 필요' 표시(빈 값 = 해제)."""
    try:
        return success(item=await competitor_queue.watch_upsert(body))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("점검 설정 저장", e)


@router.post("/bulk")
async def upsert_bulk(body: CompetitorBulk, auth=Depends(require_feature(Feature.RESEARCH))):
    out, errors = [], []
    # 확인할 때의 우리 쪽 값(판매가 · 원가 · 옵션명)을 같이 남긴다 — 대기열 '바뀜' 판정 기준 (2026-11-19)
    try:
        snaps = await snapshots({it.product_id for it in body.items})
    except Exception as e:
        logger.error(f"최저가 경쟁 기준값 계산 실패: {type(e).__name__}")
        snaps = {}
    for it in body.items:
        try:
            out.append(await CompetitorService.upsert(it, snaps.get((it.product_id, it.platform, it.option_id))))
        except HTTPException as e:
            errors.append({"product_id": it.product_id, "platform": it.platform, "detail": e.detail})
        except Exception as e:
            logger.error(f"최저가 경쟁 일괄 저장 실패: pid={it.product_id} {type(e).__name__}")
            errors.append({"product_id": it.product_id, "platform": it.platform, "detail": "저장 실패"})
    return success(saved=len(out), errors=errors)


@router.delete("/{cid}")
async def delete_competitor(cid: int, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        await CompetitorService.delete(cid)
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e)
