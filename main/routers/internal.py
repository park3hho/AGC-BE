"""/internal/company — 같은 PC 의 다른 서비스(FIN · MKT · SHOP) 전용 회사 정보 조회 (core/internal_services.py).

  · 인증: 서비스 키 (헤더 X-API-Key, api_key.service 가 채워진 키) — core/auth_deps.require_service
  · 밖에서는 못 들어온다: nginx 가 /internal/ 을 404 로 막고, nginx 를 거친 요청(X-Real-IP)도 앱에서 404.
  · 호출 주소: http://agc_app:8000/internal/company/...  (Docker 네트워크 be_default)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from core.auth_deps import require_service
from core.response_utils import success
from services.company_account.internal_service import InternalCompanyService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/company", tags=["Internal"], include_in_schema=False)

# ⚠️ 이 파일의 로그에는 값·예외 메시지를 남기지 않는다 (비밀값이 섞일 수 있음).


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/accounts")
async def list_accounts(svc=Depends(require_service)):
    try:
        return success(service=svc["service"], items=await InternalCompanyService.list_accounts(svc["service"]))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"내부 계정 목록 실패: service={svc['service']} {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/accounts/{account_id}/password")
async def account_password(account_id: int, request: Request, svc=Depends(require_service)):
    try:
        pw = await InternalCompanyService.account_password(
            svc["service"], account_id, svc["user_id"], _client_ip(request)
        )
        logger.info(f"내부 비밀번호 열람: account_id={account_id} service={svc['service']}")
        return success(password=pw)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"내부 비밀번호 열람 실패: account_id={account_id} service={svc['service']} {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/api-credentials")
async def list_credentials(svc=Depends(require_service)):
    try:
        return success(service=svc["service"], items=await InternalCompanyService.list_credentials(svc["service"]))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"내부 API 키 목록 실패: service={svc['service']} {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@router.get("/api-credentials/{credential_id}/values")
async def credential_values(credential_id: int, request: Request, svc=Depends(require_service)):
    try:
        values = await InternalCompanyService.credential_values(
            svc["service"], credential_id, svc["user_id"], _client_ip(request)
        )
        logger.info(f"내부 API 키 열람: credential_id={credential_id} service={svc['service']}")
        return success(credential=values)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"내부 API 키 열람 실패: credential_id={credential_id} service={svc['service']} {type(e).__name__}")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
