"""최저가 경쟁 확인 대기열 — 매일 점검 루틴이 '무엇을 먼저 볼지'를 DB 에서 읽는다 (2026-11-19).

사용자 원칙: AI 가 세션 메모에 들고 다니던 일(다음 차례 · 대체 검색어 · 사람 확인 메모 · 건너뛰기)은 DB 와 API 로 옮기고 AI 는 읽기만 한다.

확인 1줄 = 제품 × 판매처 × 비교 옵션 (competitor_price 1줄, 아직 없으면 대표 옵션).
사유와 순서 (앞일수록 먼저):
  1 order       주문 들어옴 — 마지막 확인이 24시간보다 오래됐고 그 뒤에 그 마켓 주문이 들어온 제품
  2 changed     바뀜 — 확인 때 기준값(basis)과 지금 값이 다름: 판매가 · 원가(조사가 · 실구매가 · 운임) · 옵션/상품명,
                또는 그 뒤에 새 옵션 · 새 마켓 등록 · 손으로 단 '확인 필요' 표시
  3 new         확인 전 (신규 제품 · 옵션)
  4 retry       지난번 검색 안 됨(not_found) — 다시 찾기
  5 watch       lose · match — 경쟁자 가격 다시 보기
  6 stale       그 밖 — 오래된 순
skip_until(보류)은 4~6 에만 적용 — 주문 · 바뀜 · 신규는 보류 중이어도 올라온다.
표시는 저장(bulk)하면 저절로 풀린다: 새 checked_at 과 새 기준값이 들어가므로 같은 사유가 다시 생기지 않는다."""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from tortoise.functions import Max

from models.order.order import MarketOrder
from models.product.competitor import CompetitorWatch
from models.product.listing import MarketListing
from models.product.price_survey import ProductOption
from models.product.pricing import OptionPrice
from services.product.competitor_service import CompetitorService, basis_of

KST = timezone(timedelta(hours=9))
ORDER_FRESH_HOURS = 24        # 마지막 확인이 이보다 오래됐을 때만 '주문 들어옴'
ORDER_LOOKBACK_DAYS = 3       # 이 안에 들어온 주문만 본다
RANK = {"order": 1, "changed": 2, "new": 3, "retry": 4, "watch": 5, "stale": 6}
LABEL = {"order": "주문 들어옴", "changed": "바뀜", "new": "확인 전", "retry": "검색 안 됨 다시", "watch": "lose·match 재확인",
         "stale": "오래된 순"}
CODE_RE = re.compile(r"(PR-\d{6}-[0-9A-Z]{4})")


def _dt(s) -> Optional[datetime]:
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    return datetime.fromisoformat(s)


def _fmt(d: Optional[datetime]) -> Optional[str]:
    return d.astimezone(KST).strftime("%Y-%m-%d %H:%M") if d else None


def _won(v) -> str:
    return f"{int(v):,}원" if v is not None else "-"


def _diff(old: dict, cur: dict) -> list[dict]:
    out = []
    if old.get("our_price") != cur.get("our_price") and cur.get("our_price") is not None:
        out.append({"code": "price", "label": "판매가 바뀜", "detail": f"{_won(old.get('our_price'))} → {_won(cur.get('our_price'))}"})
    for k, name in (("buy_cny", "구매가"), ("survey_cny", "조사가"), ("ship_cny", "운임")):
        a, b = old.get(k), cur.get(k)
        if a is not None and b is not None and abs(float(a) - float(b)) >= 0.01:
            out.append({"code": "cost", "label": "원가 바뀜", "detail": f"{name} ¥{float(a):g} → ¥{float(b):g}"})
    if old.get("option") and cur.get("option") and old["option"] != cur["option"]:
        out.append({"code": "option", "label": "옵션 바뀜", "detail": f"{old['option']} → {cur['option']}"})
    if old.get("title") and cur.get("title") and old["title"] != cur["title"]:
        out.append({"code": "title", "label": "상품명 바뀜", "detail": f"{old['title']} → {cur['title']}"})
    return out


async def queue(platform: str, limit: int = 40, include_skipped: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    today = now.astimezone(KST).date()
    data = await CompetitorService.list(platform)
    pids = [r["product"]["id"] for r in data["items"]]
    code_to_pid = {r["product"]["code"]: r["product"]["id"] for r in data["items"]}

    # 손으로 적은 설정 — (제품, 옵션) 우선, 없으면 (제품, 전체)
    watches = {(w.product_id, w.option_id): w for w in await CompetitorWatch.filter(platform=platform, product_id__in=pids)}

    # 최근 주문 (그 마켓, 시험 · 취소 제외)
    orders: dict[int, list] = {}
    for o in await MarketOrder.filter(market=platform, is_test=False, ordered_at__gte=now - timedelta(days=ORDER_LOOKBACK_DAYS)).exclude(
            stage="cancelled").values("code", "seller_code", "ordered_at"):
        m = CODE_RE.search(o["seller_code"] or "")
        pid = code_to_pid.get(m.group(1)) if m else None
        if pid:
            orders.setdefault(pid, []).append(o)

    # 기준값이 없는 옛 확인용 — 시각 비교 (판매가 · 옵션 수정 시각)
    op_upd = {(r["pricing__product_id"]): r["m"] for r in await OptionPrice.filter(
        pricing__product_id__in=pids, pricing__platform=platform).annotate(m=Max("updated_at")).group_by(
        "pricing__product_id").values("pricing__product_id", "m")}
    opt_upd = {r["product_id"]: r["m"] for r in await ProductOption.filter(product_id__in=pids, deleted_at=None).annotate(
        m=Max("updated_at")).group_by("product_id").values("product_id", "m")}
    opt_new = {r["product_id"]: r["m"] for r in await ProductOption.filter(product_id__in=pids, deleted_at=None).annotate(
        m=Max("created_at")).group_by("product_id").values("product_id", "m")}
    lst_new = {r["product_id"]: r["m"] for r in await MarketListing.filter(product_id__in=pids, platform=platform).annotate(
        m=Max("created_at")).group_by("product_id").values("product_id", "m")}

    items, skipped = [], 0
    for row in data["items"]:
        p = row["product"]
        pid = p["id"]
        v = row["platforms"].get(platform)
        if not v:
            continue
        for ch in v["checks"]:
            c = ch.get("competitor")
            checked = _dt(c.get("checked_at")) if c else None
            oid = c.get("option_id") if c else None
            w = watches.get((pid, oid)) or watches.get((pid, None))
            reasons: list[dict] = []
            if not c or not checked:
                reasons.append({"code": "new", "label": "확인 전", "detail": "신규 제품 · 옵션"})
            else:
                fresh = [o for o in orders.get(pid, []) if o["ordered_at"] and o["ordered_at"] > checked]
                if fresh and now - checked > timedelta(hours=ORDER_FRESH_HOURS):
                    last = max(fresh, key=lambda o: o["ordered_at"])
                    reasons.append({"code": "order", "label": "주문 들어옴",
                                    "detail": f"{len(fresh)}건 · 최근 {last['code'] or ''} {_fmt(last['ordered_at'])}".strip(),
                                    "at": _fmt(last["ordered_at"])})
                cur = basis_of(ch, p["title"])
                if c.get("basis"):
                    reasons += _diff(c["basis"], cur)
                else:
                    if op_upd.get(pid) and op_upd[pid] > checked:
                        reasons.append({"code": "price", "label": "판매가 수정됨", "detail": f"{_fmt(op_upd[pid])} (기준값 없는 옛 확인)",
                                        "at": _fmt(op_upd[pid])})
                    if opt_upd.get(pid) and opt_upd[pid] > checked:
                        reasons.append({"code": "cost", "label": "옵션 · 원가 수정됨", "detail": f"{_fmt(opt_upd[pid])} (기준값 없는 옛 확인)",
                                        "at": _fmt(opt_upd[pid])})
                if opt_new.get(pid) and opt_new[pid] > checked:
                    reasons.append({"code": "new_option", "label": "새 옵션", "detail": _fmt(opt_new[pid]), "at": _fmt(opt_new[pid])})
                if lst_new.get(pid) and lst_new[pid] > checked:
                    reasons.append({"code": "listing", "label": "새 마켓 등록", "detail": _fmt(lst_new[pid]), "at": _fmt(lst_new[pid])})
                if w and w.flag_reason and w.flagged_at and w.flagged_at > checked:
                    reasons.append({"code": "flag", "label": "확인 필요 표시", "detail": w.flag_reason, "at": _fmt(w.flagged_at)})
                if c.get("status") == "not_found":
                    reasons.append({"code": "retry", "label": "검색 안 됨 다시", "detail": c.get("query") or ""})
                if ch.get("verdict") in ("lose", "match"):
                    reasons.append({"code": "watch", "label": f"{ch['verdict']} 재확인",
                                    "detail": f"경쟁 {_won(c.get('vendor_price'))} · 우리 {_won(ch.get('our_price'))} · 최소 {_won(ch.get('min_price'))}"})
            group = ("order" if any(r["code"] == "order" for r in reasons)
                     else "changed" if any(r["code"] in ("price", "cost", "option", "title", "new_option", "listing", "flag") for r in reasons)
                     else "new" if any(r["code"] == "new" for r in reasons)
                     else "retry" if any(r["code"] == "retry" for r in reasons)
                     else "watch" if any(r["code"] == "watch" for r in reasons)
                     else "stale")
            if group == "stale":
                reasons.append({"code": "stale", "label": "오래된 순", "detail": _fmt(checked) or ""})
            skip = bool(w and w.skip_until and w.skip_until >= today and RANK[group] >= RANK["retry"])
            if skip and not include_skipped:
                skipped += 1
                continue
            items.append({
                "rank": RANK[group], "group": group, "group_label": LABEL[group], "reasons": reasons,
                "product_id": pid, "code": p["code"], "title": p["title"], "platform": platform,
                "option_id": ch.get("option_id"), "option": ch.get("option"), "competitor_id": c.get("id") if c else None,
                "query": (w.query_override if w and w.query_override else None) or (c.get("query") if c else None) or p["title"],
                "query_source": "override" if w and w.query_override else "last" if c and c.get("query") else "title",
                "search_note": w.search_note if w else None, "user_note": w.user_note if w else None,
                "needs_user_check": bool(w and w.needs_user_check),
                "skip_until": w.skip_until.isoformat() if w and w.skip_until else None, "skipped": skip,
                "last_status": c.get("status") if c else None, "last_verdict": ch.get("verdict"),
                "last_checked_at": c.get("checked_at") if c else None,
                "our_price": ch.get("our_price"), "min_price": ch.get("min_price"),
                "vendor_name": c.get("vendor_name") if c else None, "vendor_price": c.get("vendor_price") if c else None,
                "vendor_ref": c.get("vendor_ref") if c else None,
                "_sort": (RANK[group],
                          -(max((o["ordered_at"] for o in orders.get(pid, [])), default=now).timestamp()) if group == "order" else 0,
                          checked.timestamp() if checked else 0, pid),
            })
    items.sort(key=lambda x: x["_sort"])
    counts: dict[str, int] = {}
    for it in items:
        counts[it["group"]] = counts.get(it["group"], 0) + 1
        it.pop("_sort", None)
    return {"platform": platform, "generated_at": _fmt(now), "total": len(items), "skipped": skipped, "counts": counts,
            "order": list(RANK), "items": items[:limit]}


async def watch_list(platform: Optional[str] = None) -> list[dict]:
    qs = CompetitorWatch.all()
    if platform:
        qs = qs.filter(platform=platform)
    return [watch_dict(w) for w in await qs.order_by("product_id", "platform")]


def watch_dict(w: CompetitorWatch) -> dict:
    return {"id": w.id, "product_id": w.product_id, "platform": w.platform, "option_id": w.option_id,
            "query_override": w.query_override, "search_note": w.search_note, "user_note": w.user_note,
            "needs_user_check": w.needs_user_check, "skip_until": w.skip_until.isoformat() if w.skip_until else None,
            "flag_reason": w.flag_reason, "flagged_at": _fmt(w.flagged_at), "updated_at": _fmt(w.updated_at)}


async def watch_upsert(body) -> dict:
    data = body.model_dump(exclude_unset=True)
    key = {"product_id": body.product_id, "platform": body.platform, "option_id": body.option_id}
    w = await CompetitorWatch.get_or_none(**key)
    vals = {k: data[k] for k in ("query_override", "search_note", "user_note", "needs_user_check", "skip_until") if k in data}
    for k in ("query_override", "search_note", "user_note"):
        if k in vals and vals[k] is not None:
            vals[k] = vals[k].strip() or None
    if "skip_days" in data and data["skip_days"] is not None:
        vals["skip_until"] = None if data["skip_days"] == 0 else datetime.now(KST).date() + timedelta(days=data["skip_days"])
    if "flag_reason" in data:
        r = (data["flag_reason"] or "").strip()
        vals["flag_reason"], vals["flagged_at"] = (r, datetime.now(timezone.utc)) if r else (None, None)
    if w:
        if vals:
            await CompetitorWatch.filter(id=w.id).update(**vals)
        w = await CompetitorWatch.get(id=w.id)
    else:
        w = await CompetitorWatch.create(**key, **vals)
    return watch_dict(w)
