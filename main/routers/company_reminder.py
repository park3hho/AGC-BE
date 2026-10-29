import logging

from fastapi import APIRouter, Depends

from core.auth_deps import require_auth
from core.response_utils import success
from services import hq_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/company-reminders", tags=["CompanyReminder"])


@router.get("")
async def get_company_reminders(auth=Depends(require_auth)):
    """홈 할 일 — HQ(회사 정보 정본)의 API 키 만료·재인증, 기본 정보 만료 날짜 (2026-10-30).
    회사 계정·API 키·기본 정보 화면은 HQ(hq_url)로 옮겼다. AGC 는 날짜만 읽는다."""
    return success(**await hq_client.reminders())