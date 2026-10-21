import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.api_credential import ApiCredentialCreate, ApiCredentialUpdate
from services.company_account.api_credential_service import ApiCredentialService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api-credentials", tags=["ApiCredential"])

# 회사 계정과 같은 권한을 쓴다: 보기·비밀값 열람 = account_view, 추가·수정·삭제 = account_edit
# ⚠️ 이 파일의 로그에는 예외 메시지(str(e))를 남기지 않는다 — 비밀값이 섞일 수 있다.


def _fail(what: str, e: Exception, credential_id=None):
    where = f" credential_id={credential_id}" if credential_id is not None else ""
    logger.error(f"API 키 {what} 실패:{where} {type(e).__name__}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("")
async def list_api_credentials(auth=Depends(require_feature(Feature.ACCOUNT_VIEW))):
    try:
        return success(items=await ApiCredentialService.list())
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("목록 조회", e)


@router.post("")
async def create_api_credential(body: ApiCredentialCreate, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))):
    try:
        item = await ApiCredentialService.create(body, actor_id=auth["user_id"])
        logger.info(f"API 키 추가: credential_id={item['id']} by={auth['user_id']}")
        return success(credential=item)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("추가", e)


@router.get("/{credential_id}")
async def get_api_credential(credential_id: int, auth=Depends(require_feature(Feature.ACCOUNT_VIEW))):
    try:
        return success(credential=await ApiCredentialService.get(credential_id))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("조회", e, credential_id)


@router.patch("/{credential_id}")
async def update_api_credential(
    credential_id: int, body: ApiCredentialUpdate, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))
):
    try:
        item = await ApiCredentialService.update(credential_id, body)
        logger.info(f"API 키 수정: credential_id={credential_id} fields={sorted(body.model_fields_set)} by={auth['user_id']}")
        return success(credential=item)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("수정", e, credential_id)


@router.delete("/{credential_id}")
async def delete_api_credential(credential_id: int, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))):
    try:
        await ApiCredentialService.delete(credential_id)
        logger.info(f"API 키 삭제: credential_id={credential_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("삭제", e, credential_id)


@router.get("/{credential_id}/secrets/{secret_id}")
async def reveal_api_secret(
    credential_id: int, secret_id: int, request: Request, auth=Depends(require_feature(Feature.ACCOUNT_VIEW))
):
    try:
        ip = request.client.host if request.client else None
        value = await ApiCredentialService.reveal(credential_id, secret_id, actor_id=auth["user_id"], ip=ip)
        logger.info(f"API 비밀값 열람: credential_id={credential_id} secret_id={secret_id} by={auth['user_id']}")
        return success(value=value)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("비밀값 열람", e, credential_id)
