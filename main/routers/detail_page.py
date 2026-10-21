import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from core.auth_deps import require_feature
from core.detail_page_config import DetailStatus, ExportPlatform
from core.permissions import Feature
from core.response_utils import success
from schemas.detail_page import DetailCommonSave, DetailPageApprove, DetailPageRequestChanges, DetailPageSave
from services.product.detail_export_service import read_uploads
from services.product.detail_page_service import STATUS_NONE, DetailPageService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/detail-pages", tags=["DetailPage"])

_STATUS_FILTERS = {STATUS_NONE, *(s.value for s in DetailStatus)}


def _fail(what: str, e: Exception):
    logger.error(f"상세페이지 {what} 실패: {type(e).__name__}: {e}")
    raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_detail_pages(
    status: str | None = Query(default=None, max_length=20),
    q: str | None = Query(default=None, max_length=100),
    auth=Depends(require_feature(Feature.RESEARCH)),
):
    if status and status not in _STATUS_FILTERS:
        raise HTTPException(status_code=400, detail="알 수 없는 상태입니다.")
    try:
        return success(**await DetailPageService.list(status, q))
    except HTTPException:
        raise
    except Exception as e:
        _fail("목록 조회", e)


# ★ /{product_id} 보다 먼저 선언
@router.get("/common")
async def get_common(auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(common=await DetailPageService.get_common())
    except HTTPException:
        raise
    except Exception as e:
        _fail("공통 안내 조회", e)


@router.put("/common")
async def save_common(body: DetailCommonSave, auth=Depends(require_feature(Feature.DETAIL_REVIEW))):
    # 공통 안내는 모든 상세페이지 · 등록번호에 걸려 있어 검수 권한(사람 로그인)으로만 바꾼다
    try:
        return success(**await DetailPageService.save_common(body, auth["user_id"]))
    except HTTPException:
        raise
    except Exception as e:
        _fail("공통 안내 저장", e)


@router.get("/{product_id}")
async def get_detail_page(product_id: int, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(**await DetailPageService.get(product_id))
    except HTTPException:
        raise
    except Exception as e:
        _fail("조회", e)


@router.put("/{product_id}")
async def save_detail_page(product_id: int, body: DetailPageSave, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(page=await DetailPageService.save(product_id, body, auth["user_id"]))
    except HTTPException:
        raise
    except Exception as e:
        _fail("저장", e)


@router.post("/{product_id}/approve")
async def approve_detail_page(
    product_id: int, body: DetailPageApprove, auth=Depends(require_feature(Feature.DETAIL_REVIEW))
):
    # DETAIL_REVIEW 는 API 키로 쓸 수 없다 (auth_deps.API_KEY_FEATURES) → 승인은 사람만
    try:
        return success(page=await DetailPageService.approve(product_id, body, auth["user_id"]))
    except HTTPException:
        raise
    except Exception as e:
        _fail("승인", e)


@router.post("/{product_id}/exports")
async def save_export(
    product_id: int,
    platform: ExportPlatform = Form(...),
    content_hash: str = Form(..., min_length=64, max_length=64),
    template: str = Form(default="", max_length=50),
    files: list[UploadFile] = File(...),
    auth=Depends(require_feature(Feature.DETAIL_REVIEW)),
):
    # 승인한 사람(검수 권한)이 그린 JPG 조각만 받는다 — API 키 불가
    try:
        blobs = await read_uploads(files)
        return success(export=await DetailPageService.save_export(
            product_id, platform, content_hash, template, blobs, auth["user_id"]
        ))
    except HTTPException:
        raise
    except Exception as e:
        _fail("이미지 내보내기", e)
    finally:
        for f in files:
            await f.close()


@router.post("/{product_id}/request-changes")
async def request_changes(
    product_id: int, body: DetailPageRequestChanges, auth=Depends(require_feature(Feature.DETAIL_REVIEW))
):
    try:
        return success(page=await DetailPageService.request_changes(product_id, body.note, auth["user_id"]))
    except HTTPException:
        raise
    except Exception as e:
        _fail("수정 요청", e)
