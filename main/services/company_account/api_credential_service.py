from datetime import datetime, timezone

from fastapi import HTTPException
from tortoise.transactions import in_transaction

from core.account_crypto import decrypt_secret, encrypt_secret
from models.company_account.api_credential import ApiCredential, ApiCredentialSecret, ApiCredentialSecretView
from schemas.api_credential import ApiCredentialCreate, ApiCredentialUpdate


def credential_dict(c, secrets) -> dict:
    """목록·등록·수정 응답 — 비밀값은 이름(label)만. value_enc 는 절대 넣지 않는다."""
    return {
        "id": c.id,
        "service": c.service,
        "url": c.url,
        "public_values": c.public_values or [],
        "secrets": [{"id": s.id, "label": s.label} for s in secrets],
        "issued_on": c.issued_on.isoformat() if c.issued_on else None,
        "expires_on": c.expires_on.isoformat() if c.expires_on else None,
        "reauth_from": c.reauth_from.isoformat() if c.reauth_from else None,
        "reauth_to": c.reauth_to.isoformat() if c.reauth_to else None,
        "allowed_ips": c.allowed_ips or [],
        "memo": c.memo,
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    }


def alive_credentials():
    return ApiCredential.filter(deleted_at=None)


async def _get_alive(credential_id: int) -> ApiCredential:
    c = await alive_credentials().get_or_none(id=credential_id)
    if not c:
        raise HTTPException(status_code=404, detail="API 키를 찾지 못했습니다.")
    return c


async def _secrets_of(credential_id: int, conn=None) -> list[ApiCredentialSecret]:
    qs = ApiCredentialSecret.filter(credential_id=credential_id)
    if conn is not None:
        qs = qs.using_db(conn)
    return await qs.order_by("sort", "id")


def _plain_fields(body, exclude: set) -> dict:
    data = body.model_dump(exclude_unset=True, exclude=exclude)
    if "public_values" in data:
        data["public_values"] = [{"label": p["label"], "value": p["value"]} for p in data["public_values"]]
    return data


class ApiCredentialService:
    @staticmethod
    async def list() -> list[dict]:
        rows = await alive_credentials().order_by("service", "id")
        by_cred: dict[int, list] = {r.id: [] for r in rows}
        if rows:
            for s in await ApiCredentialSecret.filter(credential_id__in=list(by_cred)).order_by("sort", "id"):
                by_cred[s.credential_id].append(s)
        return [credential_dict(r, by_cred[r.id]) for r in rows]

    @staticmethod
    async def get(credential_id: int) -> dict:
        c = await _get_alive(credential_id)
        return credential_dict(c, await _secrets_of(c.id))

    @staticmethod
    async def create(body: ApiCredentialCreate, actor_id: int) -> dict:
        data = _plain_fields(body, exclude={"secrets"})
        data.setdefault("public_values", [])
        async with in_transaction() as conn:
            c = await ApiCredential.create(**data, created_by_id=actor_id, using_db=conn)
            for i, s in enumerate(body.secrets):
                await ApiCredentialSecret.create(
                    credential_id=c.id, label=s.label, value_enc=encrypt_secret(s.value), sort=i, using_db=conn
                )
        return await ApiCredentialService.get(c.id)

    @staticmethod
    async def update(credential_id: int, body: ApiCredentialUpdate) -> dict:
        data = _plain_fields(body, exclude={"secrets"})
        if not data and body.secrets is None:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        c = await _get_alive(credential_id)
        async with in_transaction() as conn:
            if data:
                await c.update_from_dict(data).save(using_db=conn)
            if body.secrets is not None:
                old = {s.label: s for s in await _secrets_of(c.id, conn)}
                keep_ids = set()
                for i, s in enumerate(body.secrets):
                    prev = old.get(s.label)
                    if s.value is None and prev is None:
                        raise HTTPException(status_code=400, detail=f"새 비밀값 '{s.label}' 의 값을 입력해주세요.")
                    if prev:
                        # 같은 이름은 같은 행을 고친다 — 열람 기록이 이어지게
                        prev.sort = i
                        if s.value is not None:
                            prev.value_enc = encrypt_secret(s.value)
                        await prev.save(using_db=conn)
                        keep_ids.add(prev.id)
                    else:
                        new = await ApiCredentialSecret.create(
                            credential_id=c.id, label=s.label, value_enc=encrypt_secret(s.value), sort=i,
                            using_db=conn,
                        )
                        keep_ids.add(new.id)
                drop = [s.id for s in old.values() if s.id not in keep_ids]
                if drop:
                    await ApiCredentialSecret.filter(id__in=drop).using_db(conn).delete()
            await c.save(update_fields=["updated_at"], using_db=conn)
        return await ApiCredentialService.get(c.id)

    @staticmethod
    async def delete(credential_id: int) -> None:
        c = await _get_alive(credential_id)
        c.deleted_at = datetime.now(timezone.utc)
        await c.save(update_fields=["deleted_at", "updated_at"])

    @staticmethod
    async def reveal(credential_id: int, secret_id: int, actor_id: int, ip: str | None) -> str:
        """비밀값 한 개 복호화 + 열람 기록. 기록을 못 남기면 값도 주지 않는다."""
        async with in_transaction():
            c = await alive_credentials().get_or_none(id=credential_id)
            s = await ApiCredentialSecret.get_or_none(id=secret_id, credential_id=credential_id) if c else None
            if not s:
                raise HTTPException(status_code=404, detail="비밀값을 찾지 못했습니다.")
            await ApiCredentialSecretView.create(secret_id=s.id, user_id=actor_id, ip=(ip or None) and ip[:64])
            return decrypt_secret(s.value_enc)


async def credential_values(service: str) -> tuple[dict, dict]:
    """서버 안에서 외부 API 를 부를 때만 쓴다 — (공개값 {label: value}, 비밀값 {label: 평문}).
    사람이 보는 열람(reveal)이 아니라 열람 기록은 남기지 않는다. 반환값을 응답·로그에 넣지 말 것."""
    c = await alive_credentials().filter(service=service).first()
    if not c:
        raise HTTPException(status_code=503, detail=f"'{service}' API 키가 등록되지 않았습니다.")
    public = {p["label"]: p["value"] for p in (c.public_values or [])}
    secrets = {s.label: decrypt_secret(s.value_enc) for s in await _secrets_of(c.id)}
    return public, secrets
