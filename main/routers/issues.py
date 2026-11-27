"""이슈 리포트 API (2026-11-27) — 권한 order (API 키 포함: 점검 루틴이 새 이슈를 읽고 보고 표시)."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.response_utils import success
from routers.ops import require_ops
from services.ops import issues as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/issues", tags=["Issues"])


class IssuePatch(BaseModel):
    status: Optional[str] = None
    memo: Optional[str] = Field(default=None, max_length=2000)
    reported: Optional[bool] = None


@router.get("")
async def list_issues(kind: Optional[str] = None, status: Optional[str] = None, unreported: bool = False,
                      page: int = Query(default=1, ge=1), size: int = Query(default=30, ge=1, le=200),
                      auth=Depends(require_ops)):
    return success(**await svc.list_issues(kind, status, page, size, unreported))


@router.get("/by-option")
async def by_option(auth=Depends(require_ops)):
    return success(items={str(k): v for k, v in (await svc.open_by_option()).items()})


@router.patch("/{issue_id}")
async def patch_issue(issue_id: int, body: IssuePatch, auth=Depends(require_ops)):
    try:
        return success(**await svc.patch(issue_id, body.model_dump(exclude_unset=True)))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"이슈 수정 실패: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
