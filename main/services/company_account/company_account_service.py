from fastapi import HTTPException
from tortoise.transactions import in_transaction

from core.account_crypto import decrypt_secret, encrypt_secret
from models.company_account.company_account import CompanyAccount, CompanyAccountPasswordView
from schemas.company_account import CompanyAccountCreate


def account_dict(a) -> dict:
    """목록·등록 응답 — password_enc 는 절대 넣지 않는다."""
    return {
        "id": a.id,
        "platform": a.platform,
        "login_id": a.login_id,
        "usages": a.usages or [],
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }


class CompanyAccountService:
    @staticmethod
    async def list(usage: str | None) -> list[dict]:
        qs = CompanyAccount.all()
        if usage:
            qs = qs.filter(usages__contains=[usage])     # Postgres jsonb @> — 배열 원소 정확히 일치
        return [account_dict(a) for a in await qs.order_by("-created_at", "-id")]

    @staticmethod
    async def create(body: CompanyAccountCreate, actor_id: int) -> dict:
        a = await CompanyAccount.create(
            platform=body.platform,
            login_id=body.login_id,
            password_enc=encrypt_secret(body.password),
            usages=body.usages,
            created_by_id=actor_id,
        )
        return account_dict(a)

    @staticmethod
    async def reveal_password(account_id: int, actor_id: int, ip: str | None) -> str:
        """비밀번호 한 건 복호화 + 열람 기록. 기록을 못 남기면 비밀번호도 주지 않는다."""
        async with in_transaction():
            a = await CompanyAccount.get_or_none(id=account_id)
            if not a:
                raise HTTPException(status_code=404, detail="계정을 찾지 못했습니다.")
            await CompanyAccountPasswordView.create(account_id=a.id, user_id=actor_id, ip=(ip or None) and ip[:64])
            return decrypt_secret(a.password_enc)
