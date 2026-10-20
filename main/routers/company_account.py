import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.auth_deps import require_feature
from core.permissions import Feature
from core.response_utils import success, success_only
from schemas.company_account import CompanyAccountCreate, CompanyAccountUpdate
from services.company_account.company_account_service import CompanyAccountService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/company-accounts", tags=["CompanyAccount"])

# ⚠️ 이 파일의 로그에는 예외 메시지(str(e))를 남기지 않는다 — DB 오류 메시지에 행 값이 섞일 수 있다.


@router.get("")
async def list_company_accounts(
    usage: str | None = Query(default=None, max_length=30),
    auth=Depends(require_feature(Feature.ACCOUNT_VIEW)),
):
    try:
        return success(items=await CompanyAccountService.list(usage.strip() if usage else None))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"회사 계정 목록 조회 실패: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.post("")
async def create_company_account(body: CompanyAccountCreate, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))):
    try:
        account = await CompanyAccountService.create(body, actor_id=auth["user_id"])
        logger.info(f"회사 계정 추가: account_id={account['id']} by={auth['user_id']}")
        return success(account=account)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"회사 계정 추가 실패: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/{account_id}")
async def get_company_account(account_id: int, auth=Depends(require_feature(Feature.ACCOUNT_VIEW))):
    try:
        return success(account=await CompanyAccountService.get(account_id))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"회사 계정 조회 실패: account_id={account_id} {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.patch("/{account_id}")
async def update_company_account(
    account_id: int, body: CompanyAccountUpdate, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))
):
    try:
        account = await CompanyAccountService.update(account_id, body)
        logger.info(f"회사 계정 수정: account_id={account_id} fields={sorted(body.model_fields_set)} by={auth['user_id']}")
        return success(account=account)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"회사 계정 수정 실패: account_id={account_id} {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.delete("/{account_id}")
async def delete_company_account(account_id: int, auth=Depends(require_feature(Feature.ACCOUNT_EDIT))):
    try:
        await CompanyAccountService.delete(account_id)
        logger.info(f"회사 계정 삭제: account_id={account_id} by={auth['user_id']}")
        return success_only()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"회사 계정 삭제 실패: account_id={account_id} {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/{account_id}/password")
async def reveal_company_account_password(
    account_id: int, request: Request, auth=Depends(require_feature(Feature.ACCOUNT_VIEW))
):
    try:
        ip = request.client.host if request.client else None
        password = await CompanyAccountService.reveal_password(account_id, actor_id=auth["user_id"], ip=ip)
        logger.info(f"회사 계정 비밀번호 열람: account_id={account_id} by={auth['user_id']}")
        return success(password=password)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"회사 계정 비밀번호 열람 실패: account_id={account_id} {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
