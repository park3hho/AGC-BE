from datetime import datetime, timezone

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from core.account_crypto import decrypt_secret, encrypt_secret
from models.company_account.company_account import CompanyAccount, CompanyAccountPasswordView
from schemas.company_account import CompanyAccountCreate, CompanyAccountUpdate


def account_dict(a) -> dict:
    """목록·등록·수정 응답 — password_enc 는 절대 넣지 않는다."""
    return {
        "id": a.id,
        "platform": a.platform,
        "login_id": a.login_id,
        "url": a.url,
        "usages": a.usages or [],
        "memo": a.memo,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
    }


def alive_accounts():
    """삭제되지 않은 계정만 — 삭제한 계정은 목록·열람·수정 모두 404."""
    return CompanyAccount.filter(deleted_at=None)


async def _get_alive(account_id: int) -> CompanyAccount:
    a = await alive_accounts().get_or_none(id=account_id)
    if not a:
        raise HTTPException(status_code=404, detail="계정을 찾지 못했습니다.")
    return a


class CompanyAccountService:
    @staticmethod
    async def list(usage: str | None) -> list[dict]:
        qs = alive_accounts()
        if usage:
            qs = qs.filter(usages__contains=[usage])     # Postgres jsonb @> — 배열 원소 정확히 일치
        return [account_dict(a) for a in await qs.order_by("platform", "-created_at", "-id")]

    @staticmethod
    async def get(account_id: int) -> dict:
        return account_dict(await _get_alive(account_id))

    @staticmethod
    async def create(body: CompanyAccountCreate, actor_id: int) -> dict:
        a = await CompanyAccount.create(
            platform=body.platform,
            login_id=body.login_id,
            password_enc=encrypt_secret(body.password),
            usages=body.usages,
            url=body.url,
            memo=body.memo,
            created_by_id=actor_id,
        )
        return account_dict(a)

    @staticmethod
    async def update(account_id: int, body: CompanyAccountUpdate) -> dict:
        data = body.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        a = await _get_alive(account_id)
        if "password" in data:
            a.password_enc = encrypt_secret(data.pop("password"))
        await a.update_from_dict(data).save()
        return account_dict(a)

    @staticmethod
    async def delete(account_id: int) -> None:
        a = await _get_alive(account_id)
        a.deleted_at = datetime.now(timezone.utc)
        await a.save(update_fields=["deleted_at", "updated_at"])

    @staticmethod
    async def reveal_password(account_id: int, actor_id: int, ip: str | None) -> str:
        """비밀번호 한 건 복호화 + 열람 기록. 기록을 못 남기면 비밀번호도 주지 않는다."""
        async with in_transaction():
            a = await alive_accounts().get_or_none(id=account_id)
            if not a:
                raise HTTPException(status_code=404, detail="계정을 찾지 못했습니다.")
            await CompanyAccountPasswordView.create(account_id=a.id, user_id=actor_id, ip=(ip or None) and ip[:64])
            return decrypt_secret(a.password_enc)
