"""회사 정보 › 기본 정보 — 항목 CRUD · 서류 파일. 파일은 PRIVATE_DIR 에 저장하고 로그인한 사람에게만 내려준다."""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile
from tortoise.transactions import in_transaction

from core.company_info_config import (
    INFO_FILE_MAX_BYTES,
    INFO_FILE_TYPES,
    INFO_FILES_MAX,
    INFO_LINKS,
    LINK_FOOD_AGENCY_REG_NO,
)
from core.config import PRIVATE_DIR
from models.company_account.company_info import CompanyInfo, CompanyInfoFile
from schemas.company_info import CompanyInfoCreate, CompanyInfoUpdate
from utils.code_gen import today_kst

_CHUNK = 1024 * 1024


def file_dict(f: CompanyInfoFile) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "size": f.size,
        "content_type": f.content_type,
        "created_at": f.created_at.isoformat(),
    }


def info_dict(i: CompanyInfo, files: list[CompanyInfoFile]) -> dict:
    return {
        "id": i.id,
        "category": i.category,
        "name": i.name,
        "value": i.value,
        "details": i.details or [],
        "issuer": i.issuer,
        "issued_on": i.issued_on.isoformat() if i.issued_on else None,
        "expires_on": i.expires_on.isoformat() if i.expires_on else None,
        "remind": i.remind,
        "url": i.url,
        "link": i.link,
        "sort": i.sort,
        "memo": i.memo,
        "files": [file_dict(f) for f in files],
        "created_at": i.created_at.isoformat(),
        "updated_at": i.updated_at.isoformat(),
    }


def alive_infos():
    return CompanyInfo.filter(deleted_at=None)


async def linked_value(link: str) -> str | None:
    """앱 연결(link)이 붙은 항목의 값. 붙은 항목이 없으면 None, 있는데 값이 비었으면 ''."""
    i = await alive_infos().filter(link=link).first()
    return None if i is None else (i.value or "")


async def _get_alive(info_id: int) -> CompanyInfo:
    i = await alive_infos().get_or_none(id=info_id)
    if not i:
        raise HTTPException(status_code=404, detail="기본 정보를 찾지 못했습니다.")
    return i


async def _check_link_free(link: str | None, self_id: int | None = None) -> None:
    if not link:
        return
    qs = alive_infos().filter(link=link)
    if self_id is not None:
        qs = qs.exclude(id=self_id)
    other = await qs.first()
    if other:
        label = next((l["label"] for l in INFO_LINKS if l["key"] == link), link)
        raise HTTPException(status_code=409, detail=f"'{label}' 연결은 이미 '{other.name}' 항목에 붙어 있습니다.")


async def _files_of(info_id: int) -> list[CompanyInfoFile]:
    return await CompanyInfoFile.filter(info_id=info_id).order_by("id")


def _plain(body) -> dict:
    data = body.model_dump(exclude_unset=True)
    if "details" in data:
        data["details"] = [{"label": d["label"], "value": d["value"]} for d in data["details"]]
    return data


async def _sync_detail_page(touched: bool, user_id: int) -> None:
    """상세페이지 S6 등록번호를 연결된 값으로 맞춘다 (바뀌면 승인된 상세페이지는 검수 대기로)."""
    if not touched:
        return
    from services.product.detail_page_service import DetailPageService   # 순환 import 피함
    await DetailPageService.sync_linked_reg_no(user_id)


def _detect_file(head: bytes) -> str | None:
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def _safe_name(name: str | None, ext: str) -> str:
    """보여주기용 파일 이름 — 경로·제어 문자를 빼고 200자로 자른다."""
    base = Path(name or "").name
    base = re.sub(r"[\x00-\x1f\\/:*?\"<>|]", "", base).strip() or f"file.{ext}"
    return base[:200]


def _abs_path(rel: str) -> Path:
    p = (PRIVATE_DIR / rel).resolve()
    if PRIVATE_DIR.resolve() not in p.parents:
        raise HTTPException(status_code=404, detail="파일을 찾지 못했습니다.")
    return p


class CompanyInfoService:
    @staticmethod
    async def list() -> dict:
        rows = await alive_infos().order_by("category", "sort", "id")
        by_info: dict[int, list] = {r.id: [] for r in rows}
        if rows:
            for f in await CompanyInfoFile.filter(info_id__in=list(by_info)).order_by("id"):
                by_info[f.info_id].append(f)
        return {"items": [info_dict(r, by_info[r.id]) for r in rows], "links": INFO_LINKS}

    @staticmethod
    async def get(info_id: int) -> dict:
        i = await _get_alive(info_id)
        return info_dict(i, await _files_of(i.id))

    @staticmethod
    async def create(body: CompanyInfoCreate, actor_id: int) -> dict:
        data = _plain(body)
        await _check_link_free(data.get("link"))
        i = await CompanyInfo.create(**data, created_by_id=actor_id)
        await _sync_detail_page(i.link == LINK_FOOD_AGENCY_REG_NO, actor_id)
        return await CompanyInfoService.get(i.id)

    @staticmethod
    async def update(info_id: int, body: CompanyInfoUpdate, actor_id: int) -> dict:
        data = _plain(body)
        if not data:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        i = await _get_alive(info_id)
        if "link" in data:
            await _check_link_free(data["link"], self_id=i.id)
        was_linked = i.link == LINK_FOOD_AGENCY_REG_NO
        await i.update_from_dict(data).save()
        await _sync_detail_page(was_linked or i.link == LINK_FOOD_AGENCY_REG_NO, actor_id)
        return await CompanyInfoService.get(i.id)

    @staticmethod
    async def delete(info_id: int, actor_id: int) -> None:
        i = await _get_alive(info_id)
        i.deleted_at = datetime.now(timezone.utc)
        await i.save(update_fields=["deleted_at", "updated_at"])
        # 연결이 풀려도 상세페이지 등록번호는 마지막 값을 그대로 둔다 (S6 에서 직접 고칠 수 있게 됨)

    # ── 서류 파일 ───────────────────────────────────────────

    @staticmethod
    async def add_file(info_id: int, file: UploadFile) -> dict:
        i = await _get_alive(info_id)
        if await CompanyInfoFile.filter(info_id=i.id).count() >= INFO_FILES_MAX:
            raise HTTPException(status_code=400, detail=f"파일은 항목마다 {INFO_FILES_MAX}개까지 올릴 수 있습니다.")
        head = await file.read(16)
        ext = _detect_file(head)
        if not ext:
            raise HTTPException(status_code=415, detail="서류는 PDF · JPG · PNG · WEBP 만 올릴 수 있습니다.")

        day = today_kst()
        rel = Path("company_info") / f"{day:%Y}" / f"{uuid.uuid4().hex}.{ext}"
        dest = PRIVATE_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = len(head)
        try:
            with dest.open("wb") as out:
                out.write(head)
                while chunk := await file.read(_CHUNK):
                    size += len(chunk)
                    if size > INFO_FILE_MAX_BYTES:
                        raise HTTPException(status_code=413, detail="서류는 20MB 까지 올릴 수 있습니다.")
                    out.write(chunk)
            f = await CompanyInfoFile.create(
                info_id=i.id,
                name=_safe_name(file.filename, ext),
                path=rel.as_posix(),
                size=size,
                content_type=INFO_FILE_TYPES[ext],
            )
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        await i.save(update_fields=["updated_at"])
        return file_dict(f)

    @staticmethod
    async def file_for_download(info_id: int, file_id: int) -> tuple[Path, CompanyInfoFile]:
        i = await _get_alive(info_id)
        f = await CompanyInfoFile.get_or_none(id=file_id, info_id=i.id)
        if not f:
            raise HTTPException(status_code=404, detail="파일을 찾지 못했습니다.")
        p = _abs_path(f.path)
        if not p.is_file():
            raise HTTPException(status_code=404, detail="파일을 찾지 못했습니다.")
        return p, f

    @staticmethod
    async def delete_file(info_id: int, file_id: int) -> None:
        i = await _get_alive(info_id)
        f = await CompanyInfoFile.get_or_none(id=file_id, info_id=i.id)
        if not f:
            raise HTTPException(status_code=404, detail="파일을 찾지 못했습니다.")
        p = _abs_path(f.path)
        async with in_transaction() as conn:
            await f.delete(using_db=conn)
            await i.save(update_fields=["updated_at"], using_db=conn)
        p.unlink(missing_ok=True)
