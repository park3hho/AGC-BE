import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success
from schemas.upload import PhotoFromUrl
from services.upload.upload_service import UploadService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/uploads", tags=["Upload"])


@router.post("/photos")
async def upload_photo(file: UploadFile = File(...), auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(**await UploadService.save_photo(file))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"사진 업로드 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
    finally:
        await file.close()


@router.post("/photos/from-url")
async def upload_photo_from_url(body: PhotoFromUrl, auth=Depends(require_feature(Feature.RESEARCH))):
    try:
        return success(**await UploadService.save_photo_from_url(body.url))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"사진 주소 저장 실패: {e}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
