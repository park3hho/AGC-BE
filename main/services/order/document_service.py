"""주문 증빙 파일 — 고객 결제에서 빠진 돈(타오바오 구매 · 집운 배송비 · 마켓 수수료 등)의 근거 서류 (2026-10-29).
파일은 PRIVATE_DIR/order_docs 에 저장하고 order 권한이 있는 사람에게만 내려준다. 올리고 지울 때 주문 추적 기록에 남긴다."""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile

from core.config import PRIVATE_DIR
from models.order.document import OrderDocument
from models.order.jiyun import JiyunShipment
from models.order.order import MarketOrder
from models.order.purchase import TaobaoPurchase
from services.order.order_service import actor_of, log_event
from utils.code_gen import today_kst

_CHUNK = 1024 * 1024
DOC_MAX_BYTES = 20 * 1024 * 1024
DOCS_PER_ORDER_MAX = 30

# 어느 비용 줄의 근거인지 — FE 주문 상세 › 금액 의 줄과 같은 이름
DOC_KINDS = {
    "purchase": "타오바오 구매 영수증",   # 주문상세 PDF · 결제 내역
    "jiyun": "집운 배송비 결제 내역",
    "market": "마켓 정산 · 수수료 내역",
    "card": "카드 · 간편결제 청구 내역",
    "other": "기타",
}
DOC_TYPES = {"pdf": "application/pdf", "jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _detect(head: bytes) -> str | None:
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
    base = Path(name or "").name
    base = re.sub(r"[\x00-\x1f\\/:*?\"<>|]", "", base).strip() or f"file.{ext}"
    return base[:200]


def _abs_path(rel: str) -> Path:
    p = (PRIVATE_DIR / rel).resolve()
    if PRIVATE_DIR.resolve() not in p.parents:
        raise HTTPException(status_code=404, detail="파일을 찾지 못했습니다.")
    return p


def doc_dict(d: OrderDocument) -> dict:
    return {
        "id": d.id,
        "kind": d.kind,
        "kind_label": DOC_KINDS.get(d.kind, d.kind),
        "purchase_id": d.purchase_id,
        "jiyun_id": d.jiyun_id,
        "name": d.name,
        "size": d.size,
        "content_type": d.content_type,
        "memo": d.memo,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "url": f"/orders/{d.order_id}/documents/{d.id}/file",
    }


async def _order(order_id: int) -> MarketOrder:
    o = await MarketOrder.get_or_none(id=order_id)
    if not o:
        raise HTTPException(status_code=404, detail="주문을 찾지 못했습니다.")
    return o


class OrderDocumentService:
    @staticmethod
    async def list(order_id: int) -> list[dict]:
        await _order(order_id)
        rows = await OrderDocument.filter(order_id=order_id, deleted_at=None).order_by("kind", "id")
        return [doc_dict(d) for d in rows]

    @staticmethod
    async def add(
        order_id: int,
        file: UploadFile,
        kind: str,
        purchase_id: int | None,
        jiyun_id: int | None,
        memo: str | None,
        auth: dict,
    ) -> dict:
        o = await _order(order_id)
        if kind not in DOC_KINDS:
            raise HTTPException(status_code=400, detail="증빙 종류가 올바르지 않습니다.")
        if purchase_id is not None and not await TaobaoPurchase.exists(id=purchase_id, order_id=o.id, deleted_at=None):
            raise HTTPException(status_code=400, detail="이 주문의 타오바오 구매가 아닙니다.")
        if jiyun_id is not None and not await JiyunShipment.exists(id=jiyun_id, order_id=o.id, deleted_at=None):
            raise HTTPException(status_code=400, detail="이 주문의 집운 기록이 아닙니다.")
        if await OrderDocument.filter(order_id=o.id, deleted_at=None).count() >= DOCS_PER_ORDER_MAX:
            raise HTTPException(status_code=400, detail=f"증빙은 주문마다 {DOCS_PER_ORDER_MAX}개까지 올릴 수 있습니다.")

        head = await file.read(16)
        ext = _detect(head)
        if not ext:
            raise HTTPException(status_code=415, detail="증빙은 PDF · JPG · PNG · WEBP 만 올릴 수 있습니다.")
        day = today_kst()
        rel = Path("order_docs") / f"{day:%Y}" / f"{uuid.uuid4().hex}.{ext}"
        dest = PRIVATE_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = len(head)
        try:
            with dest.open("wb") as out:
                out.write(head)
                while chunk := await file.read(_CHUNK):
                    size += len(chunk)
                    if size > DOC_MAX_BYTES:
                        raise HTTPException(status_code=413, detail="파일은 20MB 까지 올릴 수 있습니다.")
                    out.write(chunk)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise

        d = await OrderDocument.create(
            order_id=o.id,
            kind=kind,
            purchase_id=purchase_id,
            jiyun_id=jiyun_id,
            name=_safe_name(file.filename, ext),
            path=rel.as_posix(),
            size=size,
            content_type=DOC_TYPES[ext],
            memo=(memo or "").strip() or None,
            created_by_id=auth["user_id"],
        )
        await OrderDocumentService._event(o, "document_add", f"증빙 추가 · {DOC_KINDS[kind]} · {d.name}", d, auth)
        return doc_dict(d)

    @staticmethod
    async def file_for_download(order_id: int, doc_id: int) -> tuple[Path, OrderDocument]:
        d = await OrderDocument.get_or_none(id=doc_id, order_id=order_id, deleted_at=None)
        if not d:
            raise HTTPException(status_code=404, detail="파일을 찾지 못했습니다.")
        p = _abs_path(d.path)
        if not p.is_file():
            raise HTTPException(status_code=404, detail="파일을 찾지 못했습니다.")
        return p, d

    @staticmethod
    async def delete(order_id: int, doc_id: int, auth: dict) -> None:
        d = await OrderDocument.get_or_none(id=doc_id, order_id=order_id, deleted_at=None)
        if not d:
            raise HTTPException(status_code=404, detail="파일을 찾지 못했습니다.")
        d.deleted_at = datetime.now(timezone.utc)
        await d.save(update_fields=["deleted_at", "updated_at"])
        o = await _order(order_id)
        await OrderDocumentService._event(o, "document_delete", f"증빙 삭제 · {DOC_KINDS.get(d.kind, d.kind)} · {d.name}", d, auth)

    @staticmethod
    async def _event(o: MarketOrder, kind: str, summary: str, d: OrderDocument, auth: dict) -> None:
        # 추적 기록 — 파일 이름 · 종류만 (내용·경로는 남기지 않는다)
        await log_event(o, actor_of(auth), kind, summary[:300], {
            "document_id": d.id, "doc_kind": d.kind, "name": d.name,
            "purchase_id": d.purchase_id, "jiyun_id": d.jiyun_id,
        })