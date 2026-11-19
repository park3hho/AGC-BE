"""30분 점검 할 일 — 서버가 DB 로 계산해 종류 · 사유 · 대상과 함께 준다 (2026-11-19).

루틴은 이 목록을 위에서부터 처리하고 결과를 각 API 에 저장한다. 루틴 메모에 '다음 차례' · 'max 번호' 를 적지 않는다.
화면(오늘 할 일)도 같은 목록을 쓴다. 개인정보(이름 · 주소 · 통관부호)는 넣지 않는다."""

from datetime import datetime, timedelta, timezone

from core.ops_config import CANCEL_LOOKBACK_DAYS, STOCK_AGING_DAYS, TASK_TYPE
from models.order.bundle import JiyunBundle
from models.order.domestic import DomesticShipment
from models.order.import_decl import ImportDeclaration
from models.order.jiyun import JiyunShipment
from models.order.order import MarketOrder
from models.order.purchase import PurchasePackage, TaobaoPurchase
from models.order.stock import JiyunStock
from services.ops.deadline import LABEL as DEADLINE_LABEL, deadline_stage, stage_rank

KST = timezone(timedelta(hours=9))
LIVE = ("received", "processing")


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _kst(v):
    return v.astimezone(KST).strftime("%m-%d %H:%M") if isinstance(v, datetime) else None


async def _naver_delay_seen(o: MarketOrder) -> bool:
    """네이버 원본(raw)에 delayedDispatchReason 이 있으면 발송지연을 이미 한 것 → delay_requested_at 을 채운다."""
    if not o.raw_enc:
        return False
    try:
        import json
        from services.order.order_service import _dec
        raw = json.loads(_dec(o.raw_enc))
    except Exception:
        return False
    po = raw.get("productOrder") if isinstance(raw, dict) else None
    reason = (po or {}).get("delayedDispatchReason") or (raw.get("delayedDispatchReason") if isinstance(raw, dict) else None)
    if not reason and isinstance(raw, dict):
        reason = "delayedDispatchReason" in json.dumps(raw, ensure_ascii=False) and "OVERSEA_DELIVERY" in json.dumps(raw)
    if not reason:
        return False
    o.delay_requested_at = o.last_synced_at or datetime.now(timezone.utc)
    await o.save(update_fields=["delay_requested_at", "updated_at"])
    return True


def _task(type_: str, orders: list, reason: str, detail: str | None = None, target: dict | None = None, **extra) -> dict:
    label, group, prio = TASK_TYPE[type_]
    return {"type": type_, "label": label, "group": group, "priority": prio,
            "order_ids": [o.id for o in orders], "order_codes": [o.code for o in orders],
            "target": target or ({"kind": "order", "id": orders[0].id, "code": orders[0].code} if orders else None),
            "reason": reason, "detail": detail, **extra}


async def compute(include_test: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    items: list[dict] = []

    orders = await MarketOrder.filter(stage__in=LIVE).order_by("id")
    by_id = {o.id: o for o in orders}
    real = [o for o in orders if include_test or not o.is_test]
    ids = [o.id for o in orders]

    purchases = await TaobaoPurchase.filter(order_id__in=ids, deleted_at=None).order_by("id") if ids else []
    buys: dict[int, list] = {}
    for p in purchases:
        if p.cn_status != "cancelled":
            buys.setdefault(p.order_id, []).append(p)
    ships = await JiyunShipment.filter(order_id__in=ids, deleted_at=None).exclude(status="cancelled").order_by("id") if ids else []
    jy: dict[int, list] = {}
    for j in ships:
        jy.setdefault(j.order_id, []).append(j)
    doms = await DomesticShipment.filter(order_id__in=ids, deleted_at=None).exclude(status="cancelled") if ids else []
    dom: dict[int, list] = {}
    for d in doms:
        dom.setdefault(d.order_id, []).append(d)

    def has_invoice(o) -> bool:   # 마켓에 국내 송장이 올라감
        return any(d.market_tracking_no or d.status in ("dispatched", "delivering", "delivered") for d in dom.get(o.id, []))

    # 1) 클레임 · 2) 발주확인 · 3) 네이버 발송지연 · 7) 구매
    from services.order.stock_service import StockService
    for o in real:
        if o.claim_type:
            items.append(_task("claim", [o], f"{o.claim_type} {o.claim_status or ''}".strip(),
                               o.claim_reason, since=_iso(o.claim_at)))
            continue
        if o.stage == "received" and not o.confirmed:
            items.append(_task("confirm", [o], "발주확인 전 (고객이 바로 취소할 수 있음)", f"{o.market} · {o.product_name[:40]}",
                               since=_iso(o.paid_at or o.ordered_at)))
            continue
        if o.market == "naver" and o.confirmed and not o.delay_requested_at and not has_invoice(o):
            if await _naver_delay_seen(o):   # 마켓 원본에 이미 발송지연이 있으면 기록만 채우고 넘어감
                continue
            items.append(_task("naver_delay", [o], "네이버 발송지연(OVERSEA_DELIVERY) 아직 안 함",
                               "주문일+14일로 1회 — 끝나면 POST /ops/orders/{id}/mark {delay_requested_at}"))
        if o.confirmed and not buys.get(o.id) and not jy.get(o.id):
            stock = []
            try:
                stock = await StockService.match(o.id)
            except Exception:
                pass
            items.append(_task("purchase", [o], "타오바오 구매 기록 없음",
                               f"{o.product_name[:40]} · {o.option_name or ''} ×{o.quantity}"
                               + (f" · 집운 재고 {len(stock)}개 있음 → 사지 말고 재고 사용" if stock else ""),
                               seller_code=o.seller_code, stock_ids=[s["id"] for s in stock]))

    # 4) 수입신고 낼 B/L · 5) 낸 신고 처리 확인
    try:
        from services.order.import_decl_service import ImportDeclService
        for g in await ImportDeclService.pending():
            os_ = [by_id.get(x["id"]) or await MarketOrder.get(id=x["id"]) for x in g["orders"]]
            items.append(_task("import_decl", os_, f"B/L {g['bl_no']} 신고 없음 (통관 전에 사전신고)",
                               f"출고 {g.get('dispatched_at') or '-'} · 통관 {g.get('customs_status') or '조회 전'}",
                               target={"kind": "bl", "id": None, "code": g["bl_no"]}))
    except Exception as e:   # 신고 목록 실패가 할 일 전체를 막지 않게
        items.append(_task("import_decl", [], "수입신고 대기 목록 계산 실패", f"{type(e).__name__}", target={"kind": "bl", "id": None, "code": None}))
    for d in await ImportDeclaration.filter(deleted_at=None, status__in=["sent", "accepted", "fix"]).prefetch_related("orders").order_by("id"):
        os_ = [o for o in d.orders if include_test or not o.is_test]
        if not os_ and not include_test:
            continue
        why = {"sent": "전송완료 → 접수·수리·오류통보 확인", "accepted": "접수 → 수리 확인", "fix": "보완요청 → 고쳐서 다시"}[d.status]
        items.append(_task("import_status", os_, why, f"{d.decl_no or '-'} · B/L {d.bl_no or '-'}",
                           target={"kind": "decl", "id": d.id, "code": d.decl_no}, since=_iso(d.updated_at)))

    # 6) 취소 뒤 환불 · 재고 처리 (최근 N일 취소, 구매가 살아 있는데 환불·재고 기록 없음)
    since = now - timedelta(days=CANCEL_LOOKBACK_DAYS)
    cancelled = await MarketOrder.filter(stage="cancelled", claim_at__gte=since).order_by("id")
    c_ids = [o.id for o in cancelled if include_test or not o.is_test]
    if c_ids:
        held = set(await JiyunStock.filter(deleted_at=None, purchase__order_id__in=c_ids).values_list("purchase_id", flat=True))
        for p in await TaobaoPurchase.filter(order_id__in=c_ids, deleted_at=None).exclude(cn_status="cancelled").prefetch_related("order"):
            if p.id in held or p.refund_status != "none" or (p.memo and "[退款" in p.memo):
                continue
            o = p.order
            where = {"ordered": "판매처 발송 전 → 退款", "shipped": "운송 중 → 집운 재고로 (또는 拦截)",
                     "arrived": "창고 입고 → 집운 재고로", "problem": "문제 상태 → 확인"}.get(p.cn_status, p.cn_status)
            items.append(_task("cancel_followup", [o], f"취소됨({_kst(o.claim_at)}) · {where}",
                               f"구매 {p.id} 타오바오 {p.taobao_order_no}",
                               target={"kind": "purchase", "id": p.id, "code": p.taobao_order_no}))

    # 8) 집운 결제 안내 / 사용자 결제 대기 — 묶음 기준
    from services.order.bundle_service import bundle_dict
    for b in await JiyunBundle.filter(status__in=["open", "confirmed"]).order_by("id"):
        if b.is_test and not include_test:
            continue
        d = await bundle_dict(b)
        if not d["size"]:
            continue
        b_orders = [by_id[i] for i in await MarketOrder.filter(jiyun_bundle_id=b.id).exclude(stage="cancelled").values_list("id", flat=True) if i in by_id]
        if not b_orders or any(jy.get(o.id) for o in b_orders):
            continue
        # 소포 여러 개로 온 구매는 전부 입고돼야 함 (purchase_package · package_count)
        partial = []
        for o in b_orders:
            for p in buys.get(o.id, []):
                if p.package_count and p.package_count > 1:
                    got = await PurchasePackage.filter(purchase_id=p.id, status="arrived").count()
                    if got < p.package_count:
                        partial.append(f"구매 {p.id} 소포 {got}/{p.package_count}")
        if d["ready"] and not partial:
            if b.notified_at:
                items.append(_task("jiyun_pay_wait", b_orders, f"안내함 {_kst(b.notified_at)} · 사용자 집운 결제 대기",
                                   b.notice_note, target={"kind": "bundle", "id": b.id, "code": b.code}, since=_iso(b.notified_at)))
            else:
                items.append(_task("jiyun_pay_notice", b_orders, f"묶음 소포 {d['arrived']}/{d['total']} 전부 입고 → 집운 결제 안내",
                                   "안내 전 그 고객 주소 置顶 · 끝나면 POST /ops/bundles/{code}/notified",
                                   target={"kind": "bundle", "id": b.id, "code": b.code}))
        elif d["arrived"] or partial:
            items.append(_task("cn_track", b_orders, f"묶음 소포 {d['arrived']}/{d['total']} 입고 — 나머지 기다림",
                               ", ".join(partial) or None, target={"kind": "bundle", "id": b.id, "code": b.code}))

    # 8-2) 남은 소포 — 주문에 집운 기록이 있는데, 어느 집운 packages 에도 안 들어간 입고 소포(두 번째 박스 등)
    #      → 그 소포만 따로 집운 결제 안내 (11-19 Manager2 지적, OR-261117-0001). 안내했는지는 알림 key jiyun_pay_needed:package:{id}
    from models.ops.alert import AgentAlert
    for o in real:
        if not jy.get(o.id):
            continue
        in_jy = {str(n).replace(" ", "") for j in jy[o.id] for n in (j.packages or [])}
        for p in buys.get(o.id, []):
            for k in await PurchasePackage.filter(purchase_id=p.id, status="arrived").order_by("id"):
                if k.tracking_no in in_jy:
                    continue
                key = f"jiyun_pay_needed:package:{k.id}"
                a = await AgentAlert.get_or_none(key=key)
                tgt = {"kind": "package", "id": k.id, "code": k.tracking_no}
                if a and a.reported_at:
                    items.append(_task("jiyun_pay_wait", [o], f"남은 소포 안내함 {_kst(a.reported_at)} · 사용자 집운 결제 대기",
                                       f"{k.courier or ''} {k.tracking_no}".strip(), target=tgt, since=_iso(a.reported_at)))
                else:
                    items.append(_task("jiyun_pay_notice", [o], "이 주문의 남은 소포 입고 → 그 소포만 따로 집운 결제 안내",
                                       f"{k.courier or ''} {k.tracking_no} · 첫 집운 {', '.join(j.jiyun_no for j in jy[o.id])} · 안내하면 알림 key {key}"
                                       + (f" · {k.memo}" if k.memo else ""), target=tgt))

    # 8-3) 열린 클레임 알림 (서버 자동 감지 auto:claims — 쿠팡 RU·UC·CC 미처리)
    for a in await AgentAlert.filter(kind="claim", resolved_at=None, source__startswith="auto:").order_by("first_at"):
        os_ = [o for o in await MarketOrder.filter(code__in=a.order_codes or [])] if a.order_codes else []
        items.append(_task("claim", os_, a.title, (a.body or "")[:300] or None,
                           target={"kind": "alert", "id": a.id, "code": a.key}, since=_iso(a.first_at)))

    # 9) 중국 물류 확인 (판매처 발송 전 · 운송 중 구매) — 묶음 단위로 이미 넣은 주문은 건너뜀
    in_bundle_track = {i for t in items if t["type"] == "cn_track" for i in t["order_ids"]}
    for o in real:
        if o.id in in_bundle_track:
            continue
        for p in buys.get(o.id, []):
            if p.cn_status in ("ordered", "shipped"):
                pk = await PurchasePackage.filter(purchase_id=p.id).order_by("id")
                if pk:
                    got = sum(1 for k in pk if k.status == "arrived")
                    need = max(len(pk), p.package_count or 0)
                    left = ", ".join(f"{k.courier or ''} {k.tracking_no}".strip() + (f" ({k.last_text})" if k.last_text else "")
                                     for k in pk if k.status != "arrived")
                    detail = f"소포 {got}/{need} 입고 · 남은 것: {left or '기록 안 된 소포'}"
                else:
                    detail = p.cn_last_text or (f"{p.cn_courier or ''} {p.cn_tracking_no or ''}".strip() or None)
                items.append(_task("cn_track", [o], {"ordered": "판매처 발송 전", "shipped": "운송 중"}[p.cn_status],
                                   detail,
                                   target={"kind": "purchase", "id": p.id, "code": p.taobao_order_no},
                                   since=_iso(p.status_checked_at or p.updated_at)))

    # 10) 집운 출고 확인 · 송장 → 마켓 발송처리
    for o in real:
        for j in jy.get(o.id, []):
            if j.status == "requested":
                items.append(_task("dispatch_check", [o], "집운 결제됨 · 출고 전", f"{j.jiyun_no}",
                                   target={"kind": "jiyun", "id": j.id, "code": j.jiyun_no}, since=_iso(j.requested_at)))
            elif j.status == "dispatched" and not has_invoice(o):
                why = f"국내 송장 {j.kr_courier or ''} {j.kr_tracking_no} → 마켓 발송처리" if j.kr_tracking_no \
                    else f"출고됨 · 국내 송장 없음 (B/L {j.hbl or '-'})"
                items.append(_task("invoice", [o], why, None, target={"kind": "jiyun", "id": j.id, "code": j.jiyun_no},
                                   since=_iso(j.dispatched_at)))

    # 11) 발송기한 (테스트 주문 포함, 마켓에 송장 없는 것)
    for o in orders:
        if o.claim_type or has_invoice(o):
            continue
        st = deadline_stage(o.ship_due_at, now)
        if not st:
            continue
        alerted = stage_rank(o.deadline_stage) >= stage_rank(st["stage"])
        items.append(_task("deadline", [o], f"{DEADLINE_LABEL.get(st['stage'], st['stage'])} · 기한 {st['due_on']}",
                           ("이미 알림" if alerted else "알릴 차례 — 알린 뒤 POST /ops/orders/{id}/mark {deadline_stage}")
                           + (" · 테스트 주문" if o.is_test else ""),
                           due_on=st["due_on"], stage=st["stage"], alerted=alerted))

    # 12) 집운 재고 14일 넘음 · 13) 환불 결과 대기
    for s in await JiyunStock.filter(deleted_at=None, status="available", created_at__lte=now - timedelta(days=STOCK_AGING_DAYS)):
        items.append(_task("stock_aging", [], f"보관 {(now - s.created_at).days}일 · {s.label[:40]}",
                           "반품(returned) 또는 손실(written_off)은 사용자 결정",
                           target={"kind": "stock", "id": s.id, "code": s.sku}))
    for p in await TaobaoPurchase.filter(deleted_at=None, refund_status="requested").prefetch_related("order"):
        if p.order.is_test and not include_test:
            continue
        items.append(_task("refund_wait", [p.order], f"退款 신청 {_kst(p.refund_requested_at)} · 결과 대기",
                           f"退款编号 {p.refund_no or '-'}", target={"kind": "purchase", "id": p.id, "code": p.taobao_order_no},
                           since=_iso(p.refund_requested_at)))

    items.sort(key=lambda t: (t["priority"], t.get("due_on") or "9999", t["order_codes"][0] if t["order_codes"] else ""))
    counts: dict[str, int] = {}
    for t in items:
        counts[t["type"]] = counts.get(t["type"], 0) + 1
    return {"generated_at": now.isoformat(), "total": len(items),
            "action": sum(1 for t in items if t["group"] == "action" and not t.get("alerted")),
            "counts": counts, "items": items}


# ------------------------------------------------------------ 회차 모드 (비용 줄이기, 2026-11-19 Manager2·사용자 "ㅇㅋ")
# 루틴은 회차 맨 앞에서 GET /ops/check-mode 를 부르고, full 일 때만 플레이북을 읽고 정식 점검을 한다.
URGENT_TYPES = ("claim", "confirm", "naver_delay", "import_decl", "cancel_followup", "purchase",
                "jiyun_pay_notice", "invoice")
DAILY_FULL_H = 4         # 강제 정식 점검은 하루 한 번 04:30 이후 첫 회차 = 04:46 (사용자 11-19 정정) — 04:00 주문 놓침 점검(risk 알림) 바로 뒤, 서버가 모르는 브라우저 변화 확인
NIGHT = range(1, 8)       # 01~07시: 할 일 없으면 skip (idle 과 같음, 표시만 다름)


async def check_mode(now: datetime | None = None) -> dict:
    """full(정식 점검) · idle(할 일 없음, 메모 없이 끝) · skip(밤 쉬는 회차) 중 하나와 이유."""
    from models.ops.alert import AgentAlert
    now = now or datetime.now(timezone.utc)
    k = now.astimezone(KST)
    t = await compute(False)
    reasons: list[str] = []
    urgent = [x for x in t["items"] if x["type"] in URGENT_TYPES]
    if t["counts"].get("stock_aging"):
        keys = {f"stock_aging:{x['target']['id']}" for x in t["items"] if x["type"] == "stock_aging"}
        seen = set(await AgentAlert.filter(key__in=list(keys)).values_list("key", flat=True))
        urgent += [x for x in t["items"] if x["type"] == "stock_aging" and f"stock_aging:{x['target']['id']}" not in seen]
    urgent += [x for x in t["items"] if x["type"] == "deadline" and not x.get("alerted")]
    if urgent:
        c: dict[str, int] = {}
        for x in urgent:
            c[x["type"]] = c.get(x["type"], 0) + 1
        reasons.append("할 일 " + " · ".join(f"{TASK_TYPE[a][0]} {n}" for a, n in c.items()))
    unrep = await AgentAlert.filter(reported_at=None, resolved_at=None).count()
    if unrep:
        reasons.append(f"안 전한 알림 {unrep}")
    since = now - timedelta(minutes=40)
    new_orders = await MarketOrder.filter(created_at__gte=since, is_test=False).count()
    new_claims = await MarketOrder.filter(claim_at__gte=since, is_test=False).count()
    if new_orders:
        reasons.append(f"새 주문 {new_orders}")
    if new_claims:
        reasons.append(f"새 클레임 {new_claims}")
    sent_decl = await ImportDeclaration.filter(deleted_at=None, status="sent").count()   # 전송 뒤 접수 전 — 오류통보는 통관 전에 고쳐야 함
    if reasons:
        mode = "full"
    elif k.hour == DAILY_FULL_H and k.minute >= 30:
        mode, reasons = "full", ["하루 한 번 정식 점검 (04:30 이후 첫 회차, 브라우저로만 보이는 변화 확인)"]
    elif (t["counts"].get("jiyun_pay_wait") or t["counts"].get("dispatch_check") or sent_decl) and k.minute < 30:
        why = [w for w, n in (("집운 결제 대기", t["counts"].get("jiyun_pay_wait")), ("출고 대기", t["counts"].get("dispatch_check")),
                               ("수입신고 접수 전", sent_decl)) if n]
        mode, reasons = "full", [" · ".join(why) + " 있음 → 매시 첫 회차 확인"]
    elif k.hour in NIGHT:
        mode, reasons = "skip", ["밤 회차 — 할 일 없음"]
    else:
        mode, reasons = "idle", ["할 일 · 새 주문 · 클레임 · 안 전한 알림 없음"]
    return {"mode": mode, "reasons": reasons, "at": now.isoformat(), "kst": k.strftime("%m-%d %H:%M"),
            "counts": t["counts"], "unreported": unrep, "new_orders": new_orders, "new_claims": new_claims}
