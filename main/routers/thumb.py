"""작은 사진 (2026-11-09 로딩 속도) — 목록의 52px 칸에 원본 사진(평균 140KB, 큰 건 1MB+)을 내려주던 것을 줄인다.

GET /thumbs/{w}/{경로}  예: /thumbs/160/photos/2026/11/abc.jpg
- /files(공개 정적 파일)와 같은 공개 범위 — uploads 안의 사진만, 경로 밖으로 못 나간다
- 처음 요청 때 webp 로 줄여 uploads/.thumbs/{w}/ 에 저장, 다음부터는 그 파일을 그대로
- 파일 이름이 uuid 라 내용이 바뀌지 않는다 → 브라우저·Cloudflare 가 1년 캐시
"""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.config import UPLOAD_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/thumbs", tags=["Thumb"])

WIDTHS = (96, 160, 320, 640)
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
CACHE = "public, max-age=31536000, immutable"
THUMB_DIR = UPLOAD_DIR / ".thumbs"


def _make(src: Path, dst: Path, w: int) -> None:
    from PIL import Image, ImageOps   # 처음 쓸 때만 불러온다

    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        im.thumbnail((w, w * 4))
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("P", "LA") else "RGB")
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".tmp")
        im.save(tmp, "WEBP", quality=78, method=4)
        tmp.replace(dst)


@router.get("/{w}/{path:path}")
async def thumb(w: int, path: str):
    if w not in WIDTHS:
        raise HTTPException(status_code=400, detail="크기가 올바르지 않습니다.")
    root = UPLOAD_DIR.resolve()
    src = (root / path).resolve()
    if root not in src.parents or src.suffix.lower() not in EXTS or ".thumbs" in src.parts:
        raise HTTPException(status_code=404, detail="파일을 찾지 못했습니다.")
    if not src.is_file():
        raise HTTPException(status_code=404, detail="파일을 찾지 못했습니다.")
    dst = THUMB_DIR / str(w) / (path + ".webp")
    if not dst.is_file():
        try:
            await asyncio.to_thread(_make, src, dst, w)
        except Exception as e:
            logger.warning(f"작은 사진 만들기 실패: {path} {type(e).__name__}")
            return FileResponse(src, headers={"Cache-Control": CACHE})   # 못 줄이면 원본이라도
    return FileResponse(dst, media_type="image/webp", headers={"Cache-Control": CACHE})
