"""이슈 리포트 (2026-11-27) — 목록 · 상태/메모 · 자동 기록(report)."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from models.ops.issue import IssueReport

KIND = {"cost_diff": "매입가 차이"}           # 늘릴 때 여기만 (measure_outlier · import_error · auth_blocked …)
STATUS = {"new": "새로", "ack": "확인함", "resolved": "해결"}


def issue_dict(i: IssueReport) -> dict:
    return {"id": i.id, "kind": i.kind, "kind_label": KIND.get(i.kind, i.kind), "status": i.status,
            "status_label": STATUS.get(i.status, i.status), "title": i.title, "detail": i.detail,
            "product_id": i.product_id, "option_id": i.option_id, "order_id": i.order_id, "order_code": i.order_code,
            "purchase_id": i.purchase_id, "data": i.data, "memo": i.memo,
            "reported_at": i.reported_at.isoformat() if i.reported_at else None,
            "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
            "created_at": i.created_at.isoformat(), "updated_at": i.updated_at.isoformat()}


async def report(kind: str, key: str, title: str, detail: str, status: str = "new", memo: str | None = None,
                 **refs) -> tuple[IssueReport, bool]:
    """같은 dedupe_key 가 있으면 내용만 새로 (상태 · 메모는 사람이 정한 것 유지). (이슈, 새로 생겼나)."""
    cur = await IssueReport.get_or_none(dedupe_key=key)
    if cur:
        if cur.detail != detail[:300] or cur.title != title[:200]:
            cur.detail, cur.title = detail[:300], title[:200]
            await cur.save(update_fields=["detail", "title", "updated_at"])
        return cur, False
    now = datetime.now(timezone.utc)
    i = await IssueReport.create(kind=kind, dedupe_key=key[:120], title=title[:200], detail=detail[:300], status=status,
                                 memo=memo, resolved_at=now if status == "resolved" else None, **refs)
    return i, True


async def list_issues(kind: Optional[str], status: Optional[str], page: int, size: int,
                      unreported: bool = False) -> dict:
    qs = IssueReport.all()
    if kind:
        qs = qs.filter(kind=kind)
    if status:
        qs = qs.filter(status=status)
    if unreported:
        qs = qs.filter(status="new", reported_at=None)
    total = await qs.count()
    rows = await qs.order_by("-created_at", "-id").offset((page - 1) * size).limit(size)
    counts = {s: await IssueReport.filter(status=s).count() for s in STATUS}
    return {"items": [issue_dict(i) for i in rows], "total": total, "page": page, "size": size,
            "counts": counts, "kinds": KIND, "statuses": STATUS}


async def patch(issue_id: int, data: dict) -> dict:
    i = await IssueReport.get_or_none(id=issue_id)
    if not i:
        raise HTTPException(status_code=404, detail="이슈를 찾지 못했어요.")
    if "status" in data and data["status"] is not None:
        if data["status"] not in STATUS:
            raise HTTPException(status_code=400, detail="상태는 new · ack · resolved 중 하나예요.")
        i.status = data["status"]
        i.resolved_at = datetime.now(timezone.utc) if i.status == "resolved" else None
    if "memo" in data:
        i.memo = (data["memo"] or "").strip()[:2000] or None
    if data.get("reported"):
        i.reported_at = datetime.now(timezone.utc)
    await i.save()
    return issue_dict(i)


async def open_by_option(option_ids: list[int] | None = None) -> dict[int, dict]:
    """옵션별 열린(새로 · 확인함) 매입가 차이 이슈 중 최신 — 가격 책정 화면 표시용."""
    qs = IssueReport.filter(kind="cost_diff", status__in=["new", "ack"], option_id__isnull=False)
    if option_ids:
        qs = qs.filter(option_id__in=option_ids)
    out: dict[int, dict] = {}
    for i in await qs.order_by("-created_at", "-id"):
        out.setdefault(i.option_id, {"id": i.id, "detail": i.detail, "status": i.status})
    return out
