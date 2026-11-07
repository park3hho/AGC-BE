import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_auth, require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.competitor import CompetitorBulk, CompetitorUpsert
from services.product.competitor_service import CompetitorService

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
        return success(item=await CompetitorService.upsert(body))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("저장", e)


@router.post("/bulk")
async def upsert_bulk(body: CompetitorBulk, auth=Depends(require_feature(Feature.RESEARCH))):
    out, errors = [], []
    for it in body.items:
        try:
            out.append(await CompetitorService.upsert(it))
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
