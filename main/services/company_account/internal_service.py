"""다른 서비스(FIN · MKT · SHOP)가 회사 계정·API 키를 조회하는 내부 경로 (core/internal_services.py).

규칙
  · 자기 서비스 이름이 shared_with 에 들어 있는 살아 있는 행만 보인다. 없으면 404 (있는지도 알려주지 않음).
  · 비밀번호·비밀값을 줄 때마다 기존 열람 기록 표에 서비스 사용자(svc-…)로 남긴다. 기록을 못 남기면 값도 안 준다.
  · 목록에는 비밀값을 넣지 않는다.
"""

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from core.account_crypto import decrypt_secret
from models.company_account.api_credential import ApiCredentialSecret, ApiCredentialSecretView
from models.company_account.company_account import CompanyAccountPasswordView
from services.company_account.api_credential_service import alive_credentials, credential_dict
from services.company_account.company_account_service import account_dict, alive_accounts


def _ip(ip: str | None) -> str | None:
    return (ip or None) and ip[:64]


class InternalCompanyService:
    @staticmethod
    async def list_accounts(service: str) -> list[dict]:
        rows = await alive_accounts().filter(shared_with__contains=[service]).order_by("platform", "id")
        return [account_dict(a) for a in rows]

    @staticmethod
    async def account_password(service: str, account_id: int, user_id: int, ip: str | None) -> str:
        async with in_transaction():
            a = await alive_accounts().filter(shared_with__contains=[service]).get_or_none(id=account_id)
            if not a:
                raise HTTPException(status_code=404, detail="계정을 찾지 못했습니다.")
            await CompanyAccountPasswordView.create(account_id=a.id, user_id=user_id, ip=_ip(ip))
            return decrypt_secret(a.password_enc)

    @staticmethod
    async def list_credentials(service: str) -> list[dict]:
        rows = await alive_credentials().filter(shared_with__contains=[service]).order_by("service", "id")
        out = []
        for c in rows:
            secrets = await ApiCredentialSecret.filter(credential_id=c.id).order_by("sort", "id")
            out.append(credential_dict(c, secrets))
        return out

    @staticmethod
    async def credential_values(service: str, credential_id: int, user_id: int, ip: str | None) -> dict:
        """공개값 {label: value} + 비밀값 {label: 평문}. 비밀값마다 열람 기록 1건."""
        async with in_transaction():
            c = await alive_credentials().filter(shared_with__contains=[service]).get_or_none(id=credential_id)
            if not c:
                raise HTTPException(status_code=404, detail="API 키를 찾지 못했습니다.")
            secrets = await ApiCredentialSecret.filter(credential_id=c.id).order_by("sort", "id")
            for s in secrets:
                await ApiCredentialSecretView.create(secret_id=s.id, user_id=user_id, ip=_ip(ip))
            return {
                "id": c.id,
                "service": c.service,
                "public": {p["label"]: p["value"] for p in (c.public_values or [])},
                "secrets": {s.label: decrypt_secret(s.value_enc) for s in secrets},
                "expires_on": c.expires_on.isoformat() if c.expires_on else None,
            }
