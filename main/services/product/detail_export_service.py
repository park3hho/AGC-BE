"""상세 이미지 내보내기 (JPG) — 승인된 상세페이지를 FE 가 판매처 폭으로 잘라 그린 JPG 조각을 받아 저장한다. BE DESIGN.md §6.4

  · 그림은 FE 가 그린다 (편집 미리보기와 같은 템플릿 · 같은 Pretendard 글꼴). BE 는 받은 조각을 검사하고 저장만 한다.
  · content_hash — 그릴 때의 content + 공통 안내 해시. 지금 해시와 다르면(그 사이에 바뀜) 받지 않는다.
  · 저장 위치: {UPLOAD_DIR}/detail/{제품 코드}/v{버전}/{코드}_{판매처}_{순번}.jpg — 버전마다 새 폴더라 덮어쓰지 않는다.
"""

import hashlib
import json
import re

from fastapi import HTTPException, UploadFile
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from core.config import UPLOAD_DIR, UPLOAD_URL_PREFIX
from core.detail_page_config import (
    EXPORT_DIR,
    EXPORT_MAX_FILES,
    EXPORT_MAX_HEIGHT,
    EXPORT_MAX_TOTAL_BYTES,
    EXPORT_WIDTHS,
    DetailStatus,
    ExportPlatform,
)
from models.product.detail_page import DetailPage, DetailPageExport

_SAFE_CODE_RE = re.compile(r"[^A-Za-z0-9_-]")
_SOF_MARKERS = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def content_hash(content: dict, common_payload: dict) -> str:
    """content + 공통 안내 → sha256 hex. 키 순서와 상관없이 같은 값이면 같은 해시."""
    raw = json.dumps({"content": content, "common": common_payload}, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """JPEG 머리(SOF)에서 (폭, 높이)를 읽는다. JPEG 가 아니거나 못 읽으면 None."""
    if not data.startswith(b"\xff\xd8"):
        return None
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:              # 채움 바이트
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in _SOF_MARKERS:
            if i + 9 > n:
                return None
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            return width, height
        if marker == 0xDA:              # 본문 시작 — SOF 를 못 찾음
            return None
        i += 2 + seg_len
    return None


def check_slices(platform: ExportPlatform, blobs: list[bytes]) -> list[dict]:
    """조각 검사 — JPEG · 판매처 폭 · 최대 높이 · 개수 · 합계 크기. 통과하면 조각별 정보."""
    if not blobs:
        raise HTTPException(status_code=400, detail="이미지 조각이 없습니다.")
    if len(blobs) > EXPORT_MAX_FILES:
        raise HTTPException(status_code=400, detail=f"이미지 조각은 {EXPORT_MAX_FILES}장까지 올릴 수 있습니다.")
    if sum(len(b) for b in blobs) > EXPORT_MAX_TOTAL_BYTES:
        raise HTTPException(status_code=413, detail="이미지 조각 합계가 10MB 를 넘습니다.")
    want = EXPORT_WIDTHS[platform]
    out = []
    for idx, b in enumerate(blobs, 1):
        size = jpeg_size(b)
        if not size:
            raise HTTPException(status_code=415, detail=f"{idx}번째 조각이 JPG 가 아닙니다.")
        w, h = size
        if w != want:
            raise HTTPException(status_code=400, detail=f"{idx}번째 조각 폭이 {w}px 입니다 ({platform.value} 는 {want}px).")
        if not 0 < h <= EXPORT_MAX_HEIGHT:
            raise HTTPException(status_code=400, detail=f"{idx}번째 조각 높이가 {h}px 입니다 (최대 {EXPORT_MAX_HEIGHT}px).")
        out.append({"width": w, "height": h, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()})
    return out


def export_dict(e: DetailPageExport, current_hash: str | None = None) -> dict:
    return {
        "platform": e.platform.value if hasattr(e.platform, "value") else e.platform,
        "version": e.version,
        "content_hash": e.content_hash,
        "current": current_hash is not None and e.content_hash == current_hash,
        "template": e.template,
        "files": e.files,
        "created_at": e.created_at.isoformat(),
        "created_by": {"id": e.created_by.id, "name": e.created_by.name} if e.created_by else None,
    }


async def latest_exports(page_id: int, current_hash: str | None) -> dict:
    """판매처별 마지막 내보내기 — {naver: {...} | None, coupang: {...} | None}"""
    out = {pf.value: None for pf in ExportPlatform}
    rows = await DetailPageExport.filter(page_id=page_id).order_by("-version", "-id").prefetch_related("created_by")
    for e in rows:
        key = e.platform.value if hasattr(e.platform, "value") else e.platform
        if out.get(key) is None:
            out[key] = export_dict(e, current_hash)
    return out


async def store_export(dp: DetailPage, product_code: str, platform: ExportPlatform, blobs: list[bytes],
                       meta: list[dict], c_hash: str, template: str, user_id: int | None) -> DetailPageExport:
    """검사를 통과한 조각을 새 버전 폴더에 쓰고 기록을 남긴다. 기록 저장이 실패하면 쓴 파일을 지운다."""
    code = _SAFE_CODE_RE.sub("_", product_code or f"page{dp.id}")
    async with in_transaction() as conn:
        last = await (DetailPageExport.filter(page_id=dp.id, platform=platform).using_db(conn)
                      .order_by("-version").first())
        version = (last.version if last else 0) + 1
        rel_dir = f"{EXPORT_DIR}/{code}/v{version}"
        dest_dir = UPLOAD_DIR / rel_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        written = []
        try:
            files = []
            for idx, (b, m) in enumerate(zip(blobs, meta), 1):
                name = f"{code}_{platform.value}_{idx:02d}.jpg"
                path = dest_dir / name
                path.write_bytes(b)
                written.append(path)
                files.append({"url": f"{UPLOAD_URL_PREFIX}/{rel_dir}/{name}", **m})
            e = await DetailPageExport.create(page_id=dp.id, platform=platform, version=version,
                                              content_hash=c_hash, template=template[:50], files=files,
                                              created_by_id=user_id, using_db=conn)
        except IntegrityError:
            for p in written:
                p.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail="동시에 내보내기가 겹쳤습니다. 다시 시도해주세요.")
        except BaseException:
            for p in written:
                p.unlink(missing_ok=True)
            raise
    return e


async def read_uploads(files: list[UploadFile]) -> list[bytes]:
    """올린 조각을 메모리로 — 합계가 한도를 넘으면 중간에 끊는다."""
    blobs, total = [], 0
    for f in files:
        data = bytearray()
        while chunk := await f.read(1024 * 1024):
            data += chunk
            total += len(chunk)
            if total > EXPORT_MAX_TOTAL_BYTES:
                raise HTTPException(status_code=413, detail="이미지 조각 합계가 10MB 를 넘습니다.")
        blobs.append(bytes(data))
    return blobs


def require_approved(dp: DetailPage) -> None:
    if dp.status != DetailStatus.APPROVED:
        raise HTTPException(status_code=400, detail="승인된 상세페이지만 이미지로 내보낼 수 있습니다.")
