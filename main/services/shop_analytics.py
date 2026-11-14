"""자사몰 분석 (2026-11-15 자사 분석도구) — 같은 DB 의 shop.shop_event(방문 기록) + shop.shop_order(결제) 를 읽어 모은다.

방문 기록은 SHOP-FE src/lib/track.js → SHOP-BE POST /track 이 쌓는다 (봇은 서버가 버림, IP 는 해시만).
- 방문자 = visitor(브라우저 무작위 id) 수, 세션 = session 수, 열람 = page_view 수
- 주문 · 매출은 방문 기록이 아니라 shop_order(결제 완료, 시험 결제 제외)가 원본
- 유입 경로 = 세션의 첫 화면(landing)의 utm_source → 없으면 referrer 호스트로 분류 → 없으면 '직접 방문'
기간은 KST 날짜 [from, to]."""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from tortoise import Tortoise

KST = timezone(timedelta(hours=9))

SOURCE_RULES = (   # (호스트에 들어 있으면, 이름)
    ("naver", "네이버"), ("google", "구글"), ("instagram", "인스타그램"), ("facebook", "페이스북"), ("fb.", "페이스북"),
    ("kakao", "카카오"), ("daum", "다음"), ("youtube", "유튜브"), ("youtu.be", "유튜브"), ("threads", "스레드"),
    ("t.co", "X(트위터)"), ("twitter", "X(트위터)"), ("x.com", "X(트위터)"), ("bing", "빙"), ("coupang", "쿠팡"),
)
UTM_NAMES = {"ig": "인스타그램", "instagram": "인스타그램", "naver": "네이버", "google": "구글", "kakao": "카카오",
             "youtube": "유튜브", "threads": "스레드", "facebook": "페이스북", "fb": "페이스북"}
PAGE_NAMES = (("/", "홈"), ("/products", "상품 목록"), ("/cart", "장바구니"), ("/order/checkout", "주문서"),
              ("/order/complete", "주문 완료"), ("/login", "로그인"), ("/signup", "회원가입"), ("/story", "스토리"))


def _source(utm: str | None, ref: str | None) -> str:
    if utm:
        return UTM_NAMES.get(utm.lower(), utm)
    if not ref:
        return "직접 방문"
    host = ref.split("/")[0].lower()
    for key, name in SOURCE_RULES:
        if key in host:
            return name
    return host.removeprefix("www.").removeprefix("m.")


def _page(path: str) -> str:
    p = (path or "/").split("?")[0]
    if p.startswith("/products/"):
        return "상품 상세"
    if p.startswith("/my"):
        return "마이페이지"
    for k, name in PAGE_NAMES:
        if p == k:
            return name
    return p


async def summary(date_from: date | None, date_to: date | None) -> dict:
    today = datetime.now(KST).date()
    d_to = date_to or today
    d_from = date_from or (d_to - timedelta(days=6))
    start = datetime.combine(d_from, datetime.min.time(), KST)
    end = datetime.combine(d_to + timedelta(days=1), datetime.min.time(), KST)
    conn = Tortoise.get_connection("default")

    ev = await conn.execute_query_dict(
        """select at, type, visitor, session, path, product_code, value, referrer, utm_source, landing, device, browser, os
           from shop.shop_event where at >= $1 and at < $2 order by at""", [start, end])
    orders = await conn.execute_query_dict(
        """select code, total_amount, paid_at from shop.shop_order
           where paid_at >= $1 and paid_at < $2 and status = 'paid' and coalesce(test, false) = false""", [start, end])
    live_since = datetime.now(timezone.utc) - timedelta(minutes=30)
    live = await conn.execute_query_dict(
        "select count(distinct visitor) as n from shop.shop_event where at >= $1", [live_since])

    # 날짜 칸 (빈 날도)
    days = {}
    d = d_from
    while d <= d_to:
        days[d.isoformat()] = {"date": d.isoformat(), "visitors": set(), "views": 0, "orders": 0, "revenue": 0}
        d += timedelta(days=1)

    sessions: dict[str, dict] = {}
    visitors, views = set(), 0
    funnel = {k: set() for k in ("page_view", "product_view", "add_to_cart", "begin_checkout", "purchase")}
    prod = defaultdict(lambda: {"views": set(), "carts": set()})
    pages = Counter()
    devices, browsers = defaultdict(set), defaultdict(set)
    for e in ev:
        day = e["at"].astimezone(KST).date().isoformat()
        v, s = e["visitor"], e["session"]
        visitors.add(v)
        funnel.setdefault(e["type"], set()).add(s)
        row = days.get(day)
        if row:
            row["visitors"].add(v)
        se = sessions.setdefault(s, {"visitor": v, "src": None, "views": 0, "first": e["at"], "last": e["at"],
                                     "carts": False, "bought": False, "n": 0})
        se["last"] = e["at"]
        se["n"] += 1
        if e["landing"] or se["src"] is None:
            if e["landing"] or e["referrer"] or e["utm_source"]:
                se["src"] = _source(e["utm_source"], e["referrer"])
        if e["type"] == "page_view":
            views += 1
            se["views"] += 1
            pages[_page(e["path"])] += 1
            if row:
                row["views"] += 1
        if e["type"] == "product_view" and e["product_code"]:
            prod[e["product_code"]]["views"].add(s)
        if e["type"] == "add_to_cart":
            se["carts"] = True
            if e["product_code"]:
                prod[e["product_code"]]["carts"].add(s)
        if e["type"] == "purchase":
            se["bought"] = True
        devices[e["device"] or "기타"].add(v)
        browsers[e["browser"] or "기타"].add(v)

    for o in orders:
        row = days.get(o["paid_at"].astimezone(KST).date().isoformat())
        if row:
            row["orders"] += 1
            row["revenue"] += o["total_amount"] or 0

    src = defaultdict(lambda: {"sessions": 0, "visitors": set(), "carts": 0, "orders": 0})
    bounce = 0
    durations = []
    for se in sessions.values():
        name = se["src"] or "직접 방문"
        src[name]["sessions"] += 1
        src[name]["visitors"].add(se["visitor"])
        src[name]["carts"] += se["carts"]
        src[name]["orders"] += se["bought"]
        bounce += se["n"] <= 1   # 화면 하나만 보고 아무것도 안 하고 나감
        durations.append((se["last"] - se["first"]).total_seconds())

    names = {}
    codes = list(prod)
    if codes:
        for r in await conn.execute_query_dict("select code, title_ko from product where code = any($1::text[])", [codes]):
            names[r["code"]] = r["title_ko"]

    n_sess = len(sessions)
    order_n = len(orders)
    revenue = sum(o["total_amount"] or 0 for o in orders)
    durations.sort()
    return {
        "range": {"from": d_from.isoformat(), "to": d_to.isoformat()},
        "live": live[0]["n"] if live else 0,
        "total": {
            "visitors": len(visitors), "sessions": n_sess, "views": views,
            "views_per_session": round(views / n_sess, 1) if n_sess else None,
            "bounce_pct": round(bounce / n_sess * 100) if n_sess else None,
            "median_sec": int(durations[len(durations) // 2]) if durations else None,
            "orders": order_n, "revenue": revenue,
            "conversion_pct": round(order_n / n_sess * 100, 1) if n_sess else None,
        },
        "funnel": [
            {"key": "page_view", "label": "방문", "sessions": len(funnel["page_view"])},
            {"key": "product_view", "label": "상품 상세", "sessions": len(funnel["product_view"])},
            {"key": "add_to_cart", "label": "장바구니·바로구매", "sessions": len(funnel["add_to_cart"])},
            {"key": "begin_checkout", "label": "결제 시도", "sessions": len(funnel["begin_checkout"])},
            {"key": "purchase", "label": "결제 완료", "sessions": len(funnel["purchase"])},
        ],
        "days": [{**r, "visitors": len(r["visitors"])} for r in days.values()],
        "sources": sorted(({"name": k, "sessions": v["sessions"], "visitors": len(v["visitors"]), "carts": v["carts"],
                            "orders": v["orders"]} for k, v in src.items()), key=lambda x: -x["sessions"]),
        "pages": [{"name": k, "views": n} for k, n in pages.most_common(10)],
        "products": sorted(({"code": c, "name": names.get(c) or c, "views": len(p["views"]), "carts": len(p["carts"])}
                            for c, p in prod.items()), key=lambda x: (-x["views"], -x["carts"]))[:15],
        "devices": sorted(({"name": k, "visitors": len(v)} for k, v in devices.items()), key=lambda x: -x["visitors"]),
        "browsers": sorted(({"name": k, "visitors": len(v)} for k, v in browsers.items()), key=lambda x: -x["visitors"]),
        "tracking_since": None if ev else await _first_event(conn),
    }


async def _first_event(conn) -> str | None:
    r = await conn.execute_query_dict("select min(at) as t from shop.shop_event")
    return r[0]["t"].isoformat() if r and r[0]["t"] else None
