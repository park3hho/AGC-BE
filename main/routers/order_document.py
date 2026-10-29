import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from services.order.document_service import DOC_KINDS, OrderDocumentService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["OrderDocument"])

# 주문 증빙 파일 (주문 상세 › 금액에서 빠진 돈을 누르면 보이는 서류). 권한은 주문과 같다 (order).


def _fail(what: str, e: Exception, order_id: int):
    logger.error(f"주문 증빙 {what} 실패: order_id={order_id} {type(e).__name__}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/{order_id}/documents")
async def list_documents(order_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        return success(items=await OrderDocumentService.list(order_id), kinds=DOC_KINDS)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록", e, order_id)


@router.post("/{order_id}/documents")
async def upload_document(
    order_id: int,
    file: UploadFile = File(...),
    kind: str = Form(...),
    purchase_id: Optional[int] = Form(default=None),
    jiyun_id: Optional[int] = Form(default=None),
    memo: Optional[str] = Form(default=None, max_length=500),
    auth=Depends(require_feature(Feature.ORDER)),
):
    try:
        d = await OrderDocumentService.add(order_id, file, kind, purchase_id, jiyun_id, memo, auth)
        logger.info(f"주문 증빙 추가: order_id={order_id} doc_id={d['id']} kind={kind} by={auth['user_id']}")
        return success(document=d)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("올리기", e, order_id)
    finally:
        await file.close()


@router.get("/{order_id}/documents/{doc_id}/file")
async def download_document(order_id: int, doc_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        path, d = await OrderDocumentService.file_for_download(order_id, doc_id)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("받기", e, order_id)
    return FileResponse(
        path,
        media_type=d.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(d.name)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{order_id}/documents/{doc_id}")
async def delete_document(order_id: int, doc_id: int, auth=Depends(require_feature(Feature.ORDER))):
    try:
        await OrderDocumentService.delete(order_id, doc_id, auth)
        logger.info(f"주문 증빙 삭제: order_id={order_id} doc_id={doc_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e, order_id)
