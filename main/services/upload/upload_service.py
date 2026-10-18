"""사진 업로드 — 이 PC 디스크(UPLOAD_DIR)에 저장하고 /files/... 주소를 돌려준다.

저장 위치: {UPLOAD_DIR}/photos/YYYY/MM/{임의 32자}.{확장자}
  · 파일 이름은 서버가 새로 만든다 — 올린 사람이 정한 이름은 쓰지 않는다 (경로 조작·덮어쓰기 방지)
  · 형식은 확장자가 아니라 파일 앞부분 바이트로 판단한다 (이름만 .jpg 인 다른 파일 차단)
"""

import uuid
from pathlib import Path

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


class UploadService:
    @staticmethod
    async def save_photo(file: UploadFile) -> dict:
        head = await file.read(16)
        ext = _detect_image_ext(head)
        if not ext:
            raise HTTPException(status_code=415, detail="사진은 JPG · PNG · WEBP · GIF 만 올릴 수 있습니다.")

        day = today_kst()
        rel = Path("photos") / f"{day:%Y}" / f"{day:%m}" / f"{uuid.uuid4().hex}.{ext}"
        dest = UPLOAD_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)

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
