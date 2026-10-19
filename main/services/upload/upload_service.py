"""사진 업로드 — 이 PC 디스크(UPLOAD_DIR)에 저장하고 /files/... 주소를 돌려준다.

저장 위치: {UPLOAD_DIR}/photos/YYYY/MM/{임의 32자}.{확장자}
  · 파일 이름은 서버가 새로 만든다 — 올린 사람이 정한 이름은 쓰지 않는다 (경로 조작·덮어쓰기 방지)
  · 형식은 확장자가 아니라 파일 앞부분 바이트로 판단한다 (이름만 .jpg 인 다른 파일 차단)
"""

import asyncio
import ipaddress
import socket
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from fastapi import HTTPException, UploadFile

from core.config import UPLOAD_DIR, UPLOAD_URL_PREFIX
from utils.code_gen import today_kst

PHOTO_MAX_BYTES = 10 * 1024 * 1024        # 10MB
_CHUNK = 1024 * 1024


def _detect_image_ext(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def _new_dest(ext: str) -> tuple[Path, Path]:
    """새 저장 경로 — photos/YYYY/MM/{임의 32자}.{확장자}. 폴더가 없으면 만든다."""
    day = today_kst()
    rel = Path("photos") / f"{day:%Y}" / f"{day:%m}" / f"{uuid.uuid4().hex}.{ext}"
    dest = UPLOAD_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    return rel, dest


class UploadService:
    @staticmethod
    async def save_photo(file: UploadFile) -> dict:
        head = await file.read(16)
        ext = _detect_image_ext(head)
        if not ext:
            raise HTTPException(status_code=415, detail="사진은 JPG · PNG · WEBP · GIF 만 올릴 수 있습니다.")

        rel, dest = _new_dest(ext)

        size = len(head)
        try:
            with dest.open("wb") as out:
                out.write(head)
                while chunk := await file.read(_CHUNK):
                    size += len(chunk)
                    if size > PHOTO_MAX_BYTES:
                        raise HTTPException(status_code=413, detail="사진은 10MB 까지 올릴 수 있습니다.")
                    out.write(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)    # 중간에 실패하면 반쯤 쓴 파일을 남기지 않는다
            raise

        return {"url": f"{UPLOAD_URL_PREFIX}/{rel.as_posix()}", "size": size}

    @staticmethod
    async def save_photo_from_url(url: str) -> dict:
        return await _save_from_url(url)


# ────────────────────────────────────────────
# 사진 주소로 저장 (POST /uploads/photos/from-url)
#   BE 가 직접 받아 오므로 서버 안쪽(127.x, 10.x, 192.168.x, 169.254.x …)을 들여다보는 데 악용될 수 있다.
#   → 연결 전에 호스트를 IP 로 풀어 공인 주소인지 확인하고, 리다이렉트는 자동으로 따라가지 않고 한 번씩 다시 검사한다.
# ────────────────────────────────────────────
FETCH_TIMEOUT_SEC = 15
FETCH_MAX_REDIRECTS = 3
_FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None     # 3xx 를 HTTPError 로 올려서 _fetch 가 직접 검사하고 따라간다


def _check_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise HTTPException(status_code=400, detail="사진 주소가 올바르지 않습니다.")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror:
        raise HTTPException(status_code=502, detail="사진 주소의 서버를 찾을 수 없습니다.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise HTTPException(status_code=400, detail="내부 주소의 사진은 받을 수 없습니다.")


def _fetch(url: str) -> bytes:
    """동기 함수 — asyncio.to_thread 로 부른다. 크기·시간 제한을 넘으면 중간에 끊는다."""
    opener = urllib.request.build_opener(_NoRedirect)
    deadline = time.monotonic() + FETCH_TIMEOUT_SEC
    for _ in range(FETCH_MAX_REDIRECTS + 1):
        _check_public_url(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HTTPException(status_code=502, detail="사진을 받는 데 시간이 너무 오래 걸립니다.")
        try:
            with opener.open(urllib.request.Request(url, headers=_FETCH_HEADERS), timeout=remaining) as resp:
                data = bytearray()
                while chunk := resp.read(_CHUNK):
                    data += chunk
                    if len(data) > PHOTO_MAX_BYTES:
                        raise HTTPException(status_code=413, detail="사진은 10MB 까지 받을 수 있습니다.")
                    if time.monotonic() > deadline:
                        raise HTTPException(status_code=502, detail="사진을 받는 데 시간이 너무 오래 걸립니다.")
                return bytes(data)
        except urllib.error.HTTPError as e:
            location = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
            if location:
                url = urljoin(url, location)
                continue
            raise HTTPException(status_code=502, detail=f"사진 서버가 오류를 돌려줬습니다 ({e.code}).")
        except (urllib.error.URLError, TimeoutError, OSError):
            raise HTTPException(status_code=502, detail="사진 서버에서 받지 못했습니다.")
    raise HTTPException(status_code=502, detail="사진 주소가 너무 여러 번 옮겨졌습니다.")


async def _save_from_url(url: str) -> dict:
    data = await asyncio.to_thread(_fetch, url)
    ext = _detect_image_ext(data[:16])
    if not ext:
        raise HTTPException(status_code=415, detail="사진 주소가 JPG · PNG · WEBP · GIF 이미지가 아닙니다.")
    rel, dest = _new_dest(ext)
    try:
        dest.write_bytes(data)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return {"url": f"{UPLOAD_URL_PREFIX}/{rel.as_posix()}", "size": len(data), "source_url": url}
