import logging

from fastapi import APIRouter, HTTPException
from tortoise import connections

from core.response_utils import success

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/health", tags=["Health"])


@router.get("")
async def health_check():
    """서버 + DB 연결 확인 (인증 불필요)."""
    try:
        await connections.get("default").execute_query("SELECT 1")
    except Exception as e:
        logger.error(f"DB 연결 확인 실패: {e}")
        raise HTTPException(status_code=503, detail="데이터베이스에 연결할 수 없습니다.")
    return success(db="ok")
