"""집운(결제 후) 동기화 — 루틴이 결제용 타오바오 탭에서 받은 집운 JSON 을 넘기면 서버가 판단한다 (2026-11-19).

루틴: 1) consolidationOrderList.json 의 secondConsoOrders 를 POST /ops/jiyun-sync {orders}
      2) 응답 need_detail 의 tradeId 마다 orderDetail.json(data) + 트레이스 글자(trace_detail.htm innerText)를
         POST /ops/jiyun-sync {orders:[], details:{tid: data}, traces:{tid: text}}
서버: 출고(已出库) → 집운 기록 dispatched + H B/L(mailNos) + 출고 시각, 알림 dispatched
      우리 기록이 없는 집운(사용자가 결제) → jiyun_trade 에 남기고 받는 곳 일치 검사 → 할 일 jiyun_record + 알림 jiyun_paid
받는 사람 원본은 저장·응답하지 않는다 (일치 결과만)."""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from models.order.bundle import JiyunBundle
from models.order.jiyun import JiyunShipment, JiyunTrade
from models.order.order import MarketOrder
from models.order.purchase import TaobaoPurchase
from services.ops.alerts import raise_alert

CN = timezone(timedelta(hours=8))
LOOKBACK_DAYS = 30
SOURCE = "auto:jiyun_sync"


def _base(no: str | None) -> str:
    return re.sub(r"-\d{1,2}$", "", (no or "").strip())


def _dec(v) -> Decimal | None:
    try:
        return Decimal(str(v)).quantize(Decimal("0.01")) if v not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


def _dispatched(o: dict) -> bool:
    d = f"{o.get('statusDesc') or ''}{o.get('statusDetail') or ''}"
    return "已出库" in d or "离开仓库" in d


def _trace_dispatch_time(text: str | None) -> datetime | None:
    """트레이스 글자에서 '包裹已出库' 시각 (중국 시각). 날짜 줄(2026-11-19…) 뒤 시각만 있는 줄도 처리."""
    if not text:
        return None
    day = None
    for line in text.splitlines():
        m = re.search(r"(\d{4}-\d{2}-\d{2})", line)
        if m:
            day = m.group(1)
        if "已出库" in line or "包裹已出库" in line:
            t = re.search(r"(\d{2}:\d{2}:\d{2})", line)
            if day and t:
                return datetime.strptime(f"{day} {t.group(1)}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=CN)
    return None


# 시·도 이름 표기 차이(전라북도↔전북특별자치도, 강원도↔강원특별자치도, 서울특별시↔서울 등)를 짧은 이름으로 맞춘다 (11-23 오탐: 전주 건)
_PROVINCE = [
    (r"서울(?:특별시|시)", "서울"), (r"부산(?:광역시|시)", "부산"), (r"대구(?:광역시|시)", "대구"), (r"인천(?:광역시|시)", "인천"),
    (r"광주(?:광역시)", "광주"), (r"대전(?:광역시|시)", "대전"), (r"울산(?:광역시|시)", "울산"), (r"세종(?:특별자치시|시)", "세종"),
    (r"경기도", "경기"), (r"강원(?:특별자치도|도)", "강원"), (r"충청북도", "충북"), (r"충청남도", "충남"),
    (r"(?:전라북도|전북특별자치도)", "전북"), (r"전라남도", "전남"), (r"경상북도", "경북"), (r"경상남도", "경남"),
    (r"제주(?:특별자치도|도)", "제주"),
]


_PROVINCE_SHORT = {"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"}


def _is_province(tok: str) -> bool:
    """주소 첫 몇 토막 중 광역 단위(도·특별시·광역시·통합특별시)인지."""
    t = re.sub(r"[\s\-(),·]", "", tok or "")
    if re.search(r"(특별자치도|특별자치시|통합특별시|특별시|광역시)$", t) or re.fullmatch(r"(경기|강원|충청북|충청남|전라북|전라남|경상북|경상남|제주)도", t):
        return True
    return t in _PROVINCE_SHORT


def _norm(s: str | None) -> str:
    s = re.sub(r"[\s\-(),·]", "", s or "")
    for pat, short in _PROVINCE:
        s = re.sub(pat, short, s)
    return s


async def _receiver_check(detail: dict, orders: list[MarketOrder]) -> tuple[str, str]:
    """상세의 받는 곳(이름 · 주소)과 그 집운에 묶인 주문 고객 비교. 원본은 밖으로 내지 않는다."""
    from services.order.order_service import receiver_full
    from services.order.pccc import mask_name
    rc = (detail or {}).get("receiver") or {}
    name, addr = _norm(rc.get("name")), _norm(rc.get("addr"))
    if not orders or not (name or addr):
        return "unknown", "비교할 주문 또는 받는 곳 정보 없음"
    notes = []
    for o in orders:
        r = receiver_full(o)
        ok_name = bool(name) and _norm(r["name"]) == name
        # 시·도 이름은 표기가 자주 바뀜다(전라북도→전북특별자치도, 전라남도→전남광주통합특별시 등) → 대조에서 빼고 시·군·구·읍·로만 본다 (11-25)
        toks = [t for t in (r["address"] or "").split() if t and not _is_province(t)][:3]   # 시·군·구 · (동/로)
        hit = [t for t in toks[:2] if _norm(t) and _norm(t) in addr]
        if ok_name and len(hit) >= min(2, len(toks)):
            return "match", f"{mask_name(r['name'])} 이름·{' '.join(toks[:2])} 일치 ({o.code})"
        notes.append(f"{o.code}: 이름 {'일치' if ok_name else '다름'} · 시/구 {len(hit)}/{min(2, len(toks))} 일치")
    return "mismatch", " / ".join(notes)[:200]


async def sync(orders: list[dict], details: dict | None, traces: dict | None, auth: dict) -> dict:
    from schemas.jiyun import JiyunBundleUpdate
    from services.order import jiyun_bundle_service as bundle_service

    details, traces = details or {}, traces or {}
    now = datetime.now(timezone.utc)
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    out = {"seen": 0, "need_detail": [], "need_trace": [], "dispatched": [], "new_paid": [], "mismatch": [], "unchanged": 0, "errors": []}

    # 목록 + (목록 없이 상세만 온 것도)
    rows = {str(o.get("orderNum")): o for o in orders if o.get("orderNum")}
    for tid in details:
        rows.setdefault(str(tid), {"orderNum": str(tid)})

    for tid, o in rows.items():
        try:
            created = None
            if o.get("createTimeStr"):
                try:
                    created = datetime.strptime(o["createTimeStr"][:10], "%Y-%m-%d").date()
                except ValueError:
                    pass
            if created and created < cutoff:
                continue
            out["seen"] += 1
            tr = await JiyunTrade.get_or_none(trade_id=tid)
            if not tr:
                tr = JiyunTrade(trade_id=tid)
            if o.get("statusDesc") is not None:
                if tr.status_desc != o.get("statusDesc"):
                    tr.status_changed_at = now
                tr.status_code, tr.status_desc = str(o.get("statusCode") or "")[:10] or None, (o.get("statusDesc") or "")[:40]
                tr.status_detail = (o.get("statusDetail") or "")[:200] or None
                tr.package_count = o.get("packageCount") or tr.package_count
                tr.fee_cny = _dec(o.get("fee")) or tr.fee_cny
                tr.weight_kg = _dec(o.get("weight")) or tr.weight_kg
                tr.created_on = created or tr.created_on
                tr.seen_at = now
            d = details.get(tid)
            if d:
                tr.lp_no = (d.get("lpNo") or tr.lp_no or "")[:60] or None
                tr.mail_nos = [str(x) for x in (d.get("mailNos") or [])][:5]
                tr.first_orders = [str(x.get("orderNum")) for x in (d.get("firstStageOrders") or []) if x.get("orderNum")][:30]
                if not o.get("statusDesc") and d.get("statusDesc"):
                    tr.status_desc = d.get("statusDesc")[:40]
                    tr.status_detail = (d.get("statusDetail") or "")[:200] or None
                tr.detail_at = now
            t_at = _trace_dispatch_time(traces.get(tid))
            if t_at:
                tr.dispatched_at = t_at
            # LP 모르면 묶음의 결제 주문번호로
            if not tr.lp_no:
                b = await JiyunBundle.get_or_none(jiyun_trade_id=tid)
                if b and b.lp_no:
                    tr.lp_no = b.lp_no
            ships = []
            if tr.lp_no:
                ships = [j for j in await JiyunShipment.filter(deleted_at=None, jiyun_no__startswith=tr.lp_no).exclude(status="cancelled")
                         if _base(j.jiyun_no) == tr.lp_no]
            is_out = _dispatched({"statusDesc": tr.status_desc, "statusDetail": tr.status_detail})

            if not tr.lp_no:
                if not d:
                    out["need_detail"].append(tid)
                await tr.save()
                continue

            if ships:
                pending = [j for j in ships if j.status == "requested"]
                if is_out and pending:
                    if not tr.mail_nos and not d:
                        out["need_detail"].append(tid)
                        await tr.save()
                        continue
                    if not tr.dispatched_at and tid not in traces:
                        out["need_trace"].append(tid)   # 출고 시각은 트레이스 페이지(다른 도메인이라 fetch 안 됨 → 탭으로 열어 글자 전달, 못 읽으면 traces:{tid:""} → 지금 시각)
                        await tr.save()
                        continue
                    hbl = tr.mail_nos[0] if tr.mail_nos else None
                    body = {"status": "dispatched", "dispatched_at": tr.dispatched_at or now}
                    if hbl and not pending[0].hbl:
                        body["hbl"] = hbl
                    await bundle_service.update_bundle(pending[0].id, JiyunBundleUpdate(**body), auth)
                    codes = [c for c in await MarketOrder.filter(id__in=[j.order_id for j in ships]).values_list("code", flat=True)]
                    await raise_alert(f"dispatched:{tr.lp_no}", "dispatched", f"집운 출고 {', '.join(codes)} — 물류번호 {hbl or '없음'}",
                                      f"{tr.lp_no} · 출고 {(tr.dispatched_at or now).astimezone(timezone(timedelta(hours=9))).strftime('%m-%d %H:%M')} KST"
                                      " · 다음: 국내 송장 → 마켓 발송처리, 수입신고 사전신고", "info", codes, tr.lp_no, SOURCE)
                    out["dispatched"].append({"trade_id": tid, "lp_no": tr.lp_no, "hbl": hbl, "orders": codes})
                else:
                    out["unchanged"] += 1
                await tr.save()
                continue

            # 우리 기록 없음 → 사용자가 결제한 집운 (또는 시험 · 다른 계정). 닫힘·취소·환불은 넘어감
            if re.search(r"关闭|取消|退款", f"{tr.status_desc or '}{tr.status_detail or '}"):
                await tr.save()
                out["unchanged"] += 1
                continue
            if not d and not tr.detail_at:
                out["need_detail"].append(tid)
                await tr.save()
                continue
            buys = await TaobaoPurchase.filter(deleted_at=None, taobao_order_no__in=tr.first_orders or ["-"]).prefetch_related("order")
            os_ = []
            for p in buys:
                if p.order and p.order not in os_:
                    os_.append(p.order)
            if d:
                tr.receiver_check, tr.receiver_note = await _receiver_check(d, os_)
            await tr.save()
            codes = [x.code for x in os_]
            level = "blocked" if tr.receiver_check == "mismatch" else "action"
            title = (f"받는 곳 불일치 의심 — 집운 결제 {', '.join(codes) or '(구매 매칭 없음)'}" if level == "blocked"
                     else f"사용자 집운 결제 — 기록 필요 {', '.join(codes) or '(구매 매칭 없음)'}")
            await raise_alert(f"jiyun_paid:{tr.lp_no}" + (":mismatch" if level == "blocked" else ""), "jiyun_paid", title,
                              f"{tr.lp_no} · 결제주문 {tid} · ¥{tr.fee_cny or '-'} · {tr.weight_kg or '-'}kg · {tr.status_desc or ''}"
                              f" · 받는 곳: {tr.receiver_note or '확인 전'}"
                              + (" · 拣货 전이면 退款/投诉 가능 — 바로 확인" if level == "blocked" else ""),
                              level, codes, tr.lp_no, SOURCE)
            (out["mismatch"] if level == "blocked" else out["new_paid"]).append(
                {"trade_id": tid, "lp_no": tr.lp_no, "orders": codes, "receiver_check": tr.receiver_check})
        except Exception as e:   # 한 건 실패가 전체를 막지 않게
            out["errors"].append(f"{tid}: {type(e).__name__}: {str(e)[:120]}")
    out["need_detail"] = sorted(set(out["need_detail"]))
    out["need_trace"] = sorted(set(out["need_trace"]))
    return out


async def unrecorded() -> list[JiyunTrade]:
    """우리 집운 기록이 없는 최근 집운 결제 (할 일 jiyun_record)."""
    cutoff = date.today() - timedelta(days=14)
    out = []
    for tr in await JiyunTrade.filter(lp_no__isnull=False, created_on__gte=cutoff).order_by("created_on"):
        ships = [j for j in await JiyunShipment.filter(deleted_at=None, jiyun_no__startswith=tr.lp_no) if _base(j.jiyun_no) == tr.lp_no]
        if not ships:
            out.append(tr)
    return out
