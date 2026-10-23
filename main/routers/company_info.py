import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.company_info import CompanyInfoCreate, CompanyInfoUpdate
from services.company_account.company_info_service import CompanyInfoService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/company-info", tags=["CompanyInfo"])

# 회사 정보 › 기본 정보. 권한은 회사 계정과 같다: 보기·파일 받기 = account_view, 추가·수정·삭제·파일 올리기 = account_edit
# 로그에는 값을 남기지 않는다 (계좌번호 등).


def _fail(what: str, e: Exception, info_id=None):
    where = f" info_id={info_id}" if info_id is not None else ""
    logger.error(f"기본 정보 {what} 실패:{where} {type(e).__name__}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_company_info(auth=Depends(require_feature(Feature.ACCOUNT_VIEW))):
    try:
        return success(**await CompanyInfoService.list())
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록 조회", e)


@router.post("")
async def create_company_info(body: CompanyInfoCreate, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))):
    try:
        item = await CompanyInfoService.create(body, actor_id=auth["user_id"])
        logger.info(f"기본 정보 추가: info_id={item['id']} by={auth['user_id']}")
        return success(item=item)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("추가", e)


@router.get("/{info_id}")
async def get_company_info(info_id: int, auth=Depends(require_feature(Feature.ACCOUNT_VIEW))):
    try:
        return success(item=await CompanyInfoService.get(info_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("조회", e, info_id)


@router.patch("/{info_id}")
async def update_company_info(
    info_id: int, body: CompanyInfoUpdate, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))
):
    try:
        item = await CompanyInfoService.update(info_id, body, actor_id=auth["user_id"])
        logger.info(f"기본 정보 수정: info_id={info_id} fields={sorted(body.model_fields_set)} by={auth['user_id']}")
        return success(item=item)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("수정", e, info_id)


@router.delete("/{info_id}")
async def delete_company_info(info_id: int, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))):
    try:
        await CompanyInfoService.delete(info_id, actor_id=auth["user_id"])
        logger.info(f"기본 정보 삭제: info_id={info_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e, info_id)


@router.post("/{info_id}/files")
async def upload_company_info_file(
    info_id: int, file: UploadFile = File(...), auth=Depends(require_feature(Feature.ACCOUNT_EDIT))
):
    try:
        f = await CompanyInfoService.add_file(info_id, file)
        logger.info(f"기본 정보 파일 추가: info_id={info_id} file_id={f['id']} by={auth['user_id']}")
        return success(file=f)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("파일 올리기", e, info_id)
    finally:
        await file.close()


@router.get("/{info_id}/files/{file_id}")
async def download_company_info_file(
    info_id: int, file_id: int, auth=Depends(require_feature(Feature.ACCOUNT_VIEW))
):
    try:
        path, f = await CompanyInfoService.file_for_download(info_id, file_id)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("파일 받기", e, info_id)
    # inline — 브라우저에서 바로 열린다 (PDF·이미지). 한글 이름은 RFC 5987 로
    return FileResponse(
        path,
        media_type=f.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(f.name)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{info_id}/files/{file_id}")
async def delete_company_info_file(info_id: int, file_id: int, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))):
    try:
        await CompanyInfoService.delete_file(info_id, file_id)
        logger.info(f"기본 정보 파일 삭제: info_id={info_id} file_id={file_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("파일 삭제", e, info_id)
