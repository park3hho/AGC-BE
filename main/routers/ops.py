"""30분 점검 규칙화 (2026-11-19) — 할 일(서버 계산) · AI 알림 기록 · 점검 상태 표시.

권한: order (API 키 포함). 루틴은 GET /ops/tasks 로 할 일을 받고, 보고 전 POST /ops/alerts 로 new 인지 확인한다."""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth_deps import require_auth
from core.permissions import has_feature
from core.ops_config import ALERT_KIND, ALERT_LEVEL, TASK_TYPE
from core.permissions import Feature
from core.response_utils import success
from models.order.bundle import JiyunBundle
from models.order.order import MarketOrder
from schemas.ops import AlertIn, AlertPatch, BundleNoticeIn, OrderMarkIn
from services.ops import alerts as alert_service
from services.ops import tasks as task_service
from services.ops.deadline import STAGES
from services.order.order_service import actor_of, log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ops", tags=["Ops"])


async def require_ops(auth: dict = Depends(require_auth)) -> dict:
    """order 권한이 있는 사용자 — API 키도 허용 (할 일 · 알림에는 고객 개인정보가 없다: 주문 코드 · 상품명 · 상태만).
    주문 원본(이름·주소·통관부호)을 주는 /orders 는 여전히 API 키 불가."""
    if not has_feature(auth["role"], Feature.ORDER):
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    return auth


def _fail(what: str, e: Exception):
    logger.error(f"ops {what} 실패: {type(e).__name__}: {e}")
    return HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


def _who(auth: dict) -> str:
    u = auth.get("user") if isinstance(auth, dict) else None
    return getattr(u, "name", None) or getattr(u, "email", None) or "agent"


@router.get("/tasks")
async def get_tasks(include_test: bool = Query(default=False), auth=Depends(require_ops)):
    try:
        data = await task_service.compute(include_test)
        return success(**data, types={k: {"label": v[0], "group": v[1], "priority": v[2]} for k, v in TASK_TYPE.items()})
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("할 일 계산", e)


@router.post("/alerts")
async def post_alert(body: AlertIn, auth=Depends(require_ops)):
    try:
        r = await alert_service.raise_alert(body.key, body.kind, body.title, body.body, body.level,
                                            body.order_codes, body.target, body.source)
        return success(**r)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("알림 기록", e)


@router.get("/alerts")
async def get_alerts(kind: Optional[str] = Query(default=None, max_length=30), open: bool = Query(default=False),
                     since: Optional[datetime] = Query(default=None), q: Optional[str] = Query(default=None, max_length=100),
                     limit: int = Query(default=100, ge=1, le=500), auth=Depends(require_ops)):
    try:
        data = await alert_service.list_alerts(kind, open, since, q, limit)
        return success(**data, kinds=ALERT_KIND, levels=ALERT_LEVEL)
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("알림 목록", e)


@router.patch("/alerts/{alert_id}")
async def patch_alert(alert_id: int, body: AlertPatch, auth=Depends(require_ops)):
    try:
        return success(alert=await alert_service.resolve(alert_id, body.resolved, _who(auth)))
    except HTTPException:
        raise
    except Exception as e:
        raise _fail("알림 처리", e)


@router.post("/orders/{order_id}/mark")
async def mark_order(order_id: int, body: OrderMarkIn, auth=Depends(require_ops)):
    """네이버 발송지연 요청 시각 · 발송기한 알린 단계를 남긴다 (보낸 칸만)."""
    o = await MarketOrder.get_or_none(id=order_id)
    if not o:
        raise HTTPException(status_code=404, detail="고객 주문을 찾지 못했습니다.")
    sent = body.model_fields_set
    if not sent:
        raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
    fields, notes = [], []
    if "delay_requested_at" in sent:
        o.delay_requested_at = body.delay_requested_at or datetime.now(timezone.utc)
        fields.append("delay_requested_at"); notes.append("네이버 발송지연 요청 기록")
    if "deadline_stage" in sent:
        st = (body.deadline_stage or "").strip() or None
        if st is not None and st not in STAGES:
            raise HTTPException(status_code=400, detail="deadline_stage 는 d3 · d1 · over 중 하나(지우려면 빈 값)예요.")
        o.deadline_stage = st
        fields.append("deadline_stage"); notes.append(f"발송기한 알림 단계 {st or '지움'}")
    await o.save(update_fields=fields + ["updated_at"])
    try:
        await log_event(o, actor_of(auth), "ops_mark", " · ".join(notes), {k: str(getattr(o, k)) for k in fields})
    except Exception:
        pass
    return success(order={"id": o.id, "code": o.code, "delay_requested_at": o.delay_requested_at.isoformat() if o.delay_requested_at else None,
                          "deadline_stage": o.deadline_stage})


@router.post("/bundles/{code}/notified")
async def bundle_notified(code: str, body: BundleNoticeIn, auth=Depends(require_ops)):
    """집운 결제 안내를 보냈다고 표시 (clear=true 면 지움). 할 일 jiyun_pay_notice → jiyun_pay_wait 로 바뀐다."""
    b = await JiyunBundle.get_or_none(code=code.strip())
    if not b:
        raise HTTPException(status_code=404, detail="묶음을 찾지 못했어요.")
    if body.clear:
        b.notified_at, b.notice_note = None, None
    else:
        b.notified_at = body.notified_at or datetime.now(timezone.utc)
        if body.note is not None:
            b.notice_note = body.note.strip() or None
    await b.save(update_fields=["notified_at", "notice_note", "updated_at"])
    return success(bundle={"code": b.code, "notified_at": b.notified_at.isoformat() if b.notified_at else None,
                           "notice_note": b.notice_note})
