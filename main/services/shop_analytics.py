"""자사몰 분석 (2026-11-15 자사 분석도구) — 같은 DB 의 shop.shop_event(방문 기록) + shop.shop_order(결제) 를 읽어 모은다.

방문 기록은 SHOP-FE src/lib/track.js → SHOP-BE POST /track 이 쌓는다 (봇은 서버가 버림, IP 는 해시만).
- 방문자 = visitor(브라우저 무작위 id) 수, 세션 = session 수, 열람 = page_view 수
- 주문 · 매출은 방문 기록이 아니라 shop_order(결제 완료, 시험 결제 제외)가 원본
- 유입 경로 = 세션의 첫 화면(landing)의 utm_source → 없으면 referrer 호스트로 분류 → 없으면 '직접 방문'
기간은 KST 날짜 [from, to]. 기본은 국내 손님만 (해외 봇 · 우리 계정 제외), all 이면 전부."""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from tortoise import Tortoise

KST = timezone(timedelta(hours=9))

# 기본 보기 = 국내 손님만 (2026-11-18 사용자: 유입 분석). all=True 면 전부.
#  - 해외 접속(country 가 KR 이 아님) 은 지금까지 전부 봇 · 크롤러였다 (11-15~11-18: 미국 · 싱가포르 · 인도, 첫 화면 0초)
#  - 몰아치기: 같은 IP 해시에서 2분 안에 새 방문자 3명 이상 = 브라우저인 척하는 수집 봇 (_burst_visitors)
#  - 우리 계정: 이메일이 @eidofood.com (테스트 · QA · 카카오페이 심사) 이거나 아래 id (대표 본인).
#    한 번이라도 이 계정으로 로그인한 브라우저(visitor)는 로그인 전 기록까지 뺀다.
INTERNAL_EMAIL_DOMAIN = "@eidofood.com"
INTERNAL_MEMBER_IDS = (3,)   # 박찬호 (대표, 개인 메일 가입)
# 로그인 없이 들어온 우리 기기 (사용자가 '나야' 확인한 방문). 앞으로는 SHOP 의 직원 기기 표시(?eido_staff=1)가 아예 안 보낸다
INTERNAL_VISITORS = (
    "2462481e-4ecc-42b9-951e-48ceb3b7bdc2",   # 2026-11-20 10:32 대표 휴대폰 (Gmail 앱 링크)
)

SOURCE_RULES = (   # (호스트에 들어 있으면, 이름) — 앞에서부터 먼저 맞는 것. 메일 · 앱 이름을 검색보다 먼저 (2026-11-20 Gmail 앱이 '구글'로 잡힘)
    ("com.google.android.gm", "이메일"), ("mail.", "이메일"), ("outlook", "이메일"),
    ("com.google.android.googlequicksearchbox", "구글"), ("com.nhn.android", "네이버"), ("com.kakao.talk", "카카오톡"),
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


BURST_WINDOW_SEC = 120   # 이 안에
BURST_MIN_VISITORS = 3   # 같은 IP(해시)에서 새 방문자가 이만큼 생기면 = 브라우저인 척하는 수집 봇


def _burst_visitors(ev: list[dict]) -> set[str]:
    """보통 브라우저 이름을 쓰는 수집 봇 — 같은 IP 해시에서 2분 안에 새 방문자(id)가 3개 이상 생기면 그 방문자들 (2026-11-18).
    사람은 같은 브라우저 id 를 유지하는데, 봇은 화면마다 저장소를 비워 매번 새 방문자가 된다 (예: 독일 2곳에서 4초에 5명)."""
    first: dict[str, tuple] = {}
    for e in ev:
        if e["visitor"] not in first and e.get("ip_hash"):
            first[e["visitor"]] = (e["ip_hash"], e["at"])
    by_ip: dict[str, list] = defaultdict(list)
    for v, (ip, at) in first.items():
        by_ip[ip].append((at, v))
    out = set()
    for rows in by_ip.values():
        rows.sort()
        for i in range(len(rows)):
            j = i
            while j + 1 < len(rows) and (rows[j + 1][0] - rows[i][0]).total_seconds() <= BURST_WINDOW_SEC:
                j += 1
            if j - i + 1 >= BURST_MIN_VISITORS:
                out.update(v for _, v in rows[i:j + 1])
    return out


async def summary(date_from: date | None, date_to: date | None, include_all: bool = False) -> dict:
    today = datetime.now(KST).date()
    d_to = date_to or today
    d_from = date_from or (d_to - timedelta(days=6))
    start = datetime.combine(d_from, datetime.min.time(), KST)
    end = datetime.combine(d_to + timedelta(days=1), datetime.min.time(), KST)
    conn = Tortoise.get_connection("default")

    internal = await conn.execute_query_dict(
        "select id from shop.member where email ilike $1 or id = any($2::int[])", [f"%{INTERNAL_EMAIL_DOMAIN}", list(INTERNAL_MEMBER_IDS)])
    internal_ids = [r["id"] for r in internal]
    ev_all = await conn.execute_query_dict(
        """select at, type, visitor, session, path, product_code, value, referrer, utm_source, landing, device, browser, os,
                  country, ip_hash, (member_id = any($3::int[])) as internal
           from shop.shop_event where at >= $1 and at < $2 order by at""", [start, end, internal_ids])
    internal_visitors = {e["visitor"] for e in ev_all if e["internal"] or e["visitor"] in INTERNAL_VISITORS}
    foreign_visitors = {e["visitor"] for e in ev_all if e["country"] and e["country"] != "KR"} - internal_visitors
    burst_visitors = _burst_visitors(ev_all) - internal_visitors - foreign_visitors
    if include_all:
        ev = ev_all
    else:
        ev = [e for e in ev_all if e["visitor"] not in internal_visitors and e["visitor"] not in burst_visitors
              and (not e["country"] or e["country"] == "KR")]
    orders = await conn.execute_query_dict(
        """select code, total_amount, paid_at from shop.shop_order
           where paid_at >= $1 and paid_at < $2 and status = 'paid' and coalesce(test, false) = false
             and ($3 or member_id is null or not (member_id = any($4::int[])))""", [start, end, include_all, internal_ids])
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
        "filter": {"all": include_all, "excluded_foreign": 0 if include_all else len(foreign_visitors),
                   "excluded_internal": 0 if include_all else len(internal_visitors),
                   "excluded_burst": 0 if include_all else len(burst_visitors)},
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
        "tracking_since": None if ev_all else await _first_event(conn),
        "traffic": await _traffic(conn, d_from, d_to),
    }


async def _first_event(conn) -> str | None:
    r = await conn.execute_query_dict("select min(at) as t from shop.shop_event")
    return r[0]["t"].isoformat() if r and r[0]["t"] else None


REASON_NAMES = {"bot": "봇", "scanner": "스캐너(취약점 찔러보기)", "rate_limit": "과다 요청", "not_found": "없는 주소",
                "empty_ua": "브라우저 정보 없음", "bad_payload": "잘못된 기록"}


async def _traffic(conn, d_from: date, d_to: date) -> dict:
    """서버로 들어온 요청 수 (SHOP-BE services/traffic.py → shop.traffic_hit, 2026-11-18~) — 정상 · 검색 봇 · 무효.
    방문 기록(shop_event)과 달리 화면을 안 그리는 봇 · 스캐너까지 센다 = 서버가 실제로 받은 부담."""
    try:
        rows = await conn.execute_query_dict(
            "select day, kind, reason, agent, country, path, hits from shop.traffic_hit where day between $1 and $2", [d_from, d_to])
    except Exception:
        return {"since": None, "total": 0, "days": [], "kinds": {}, "reasons": [], "agents": [], "paths": [], "countries": []}
    days = {}
    d = d_from
    while d <= d_to:
        days[d.isoformat()] = {"date": d.isoformat(), "valid": 0, "crawler": 0, "invalid": 0}
        d += timedelta(days=1)
    kinds, reasons, agents, paths, countries = Counter(), Counter(), Counter(), Counter(), Counter()
    crawlers = Counter()
    for r in rows:
        k, n = r["kind"], r["hits"]
        kinds[k] += n
        row = days.get(r["day"].isoformat())
        if row:
            row[k] = row.get(k, 0) + n
        if k == "crawler":
            crawlers[r["agent"]] += n
        if k == "invalid":
            reasons[r["reason"]] += n
            agents[r["agent"]] += n
            paths[r["path"]] += n
            countries[r["country"] or "?"] += n
    since = await conn.execute_query_dict("select min(day) as d from shop.traffic_hit")
    total = sum(kinds.values())
    return {
        "since": since[0]["d"].isoformat() if since and since[0]["d"] else None,
        "total": total,
        "kinds": {"valid": kinds["valid"], "crawler": kinds["crawler"], "invalid": kinds["invalid"]},
        "invalid_pct": round(kinds["invalid"] / total * 100) if total else None,
        "days": list(days.values()),
        "reasons": [{"key": k, "name": REASON_NAMES.get(k, k), "hits": n} for k, n in reasons.most_common()],
        "agents": [{"name": k, "hits": n} for k, n in agents.most_common(10)],
        "crawlers": [{"name": k, "hits": n} for k, n in crawlers.most_common(8)],
        "paths": [{"path": k, "hits": n} for k, n in paths.most_common(10)],
        "countries": [{"code": k, "hits": n} for k, n in countries.most_common(8)],
    }


async def digest(hours: int = 6) -> dict:
    """최근 N시간 자사몰 유입 요약 — 6시간마다 도는 점검이 읽는다 (2026-11-18 사용자: "API 만들어서 6시간 간격으로").
    진짜 손님(국내 · 우리 계정 아님 · 몰아치기 봇 아님)과 그 밖(해외 · 몰아치기 · 우리 계정 · 서버 무효 요청)을 나눠 센다.
    notable = 알릴 만한 일 (진짜 손님 · 검색/외부 유입 · 장바구니 이상 · 결제 완료)."""
    hours = max(1, min(hours, 168))
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    conn = Tortoise.get_connection("default")
    internal = await conn.execute_query_dict(
        "select id from shop.member where email ilike $1 or id = any($2::int[])", [f"%{INTERNAL_EMAIL_DOMAIN}", list(INTERNAL_MEMBER_IDS)])
    internal_ids = [r["id"] for r in internal]
    # 몰아치기 판정은 창 앞뒤 2분을 더 본다
    ev_all = await conn.execute_query_dict(
        """select at, type, visitor, session, path, product_code, referrer, utm_source, country, ip_hash, device, browser,
                  (member_id = any($2::int[])) as internal
           from shop.shop_event where at >= $1 order by at""", [since - timedelta(seconds=BURST_WINDOW_SEC), internal_ids])
    internal_v = {e["visitor"] for e in ev_all if e["internal"] or e["visitor"] in INTERNAL_VISITORS}
    burst_v = _burst_visitors(ev_all) - internal_v
    ev = [e for e in ev_all if e["at"] >= since]
    foreign_v = {e["visitor"] for e in ev if e["country"] and e["country"] != "KR"} - internal_v - burst_v
    real = [e for e in ev if e["visitor"] not in internal_v | burst_v | foreign_v]

    sessions: dict[str, dict] = {}
    for e in real:
        s = sessions.setdefault(e["session"], {"first": e["at"], "last": e["at"], "pages": [], "products": [], "steps": set(),
                                               "src": None, "device": e["device"], "browser": e["browser"]})
        s["last"] = e["at"]
        if s["src"] is None and (e["utm_source"] or e["referrer"]):
            s["src"] = _source(e["utm_source"], e["referrer"])
        if e["type"] == "page_view":
            s["pages"].append(_page(e["path"]))
        if e["type"] == "product_view" and e["product_code"]:
            s["products"].append(e["product_code"])
        s["steps"].add(e["type"])
    codes = sorted({c for s in sessions.values() for c in s["products"]})
    names = {}
    if codes:
        for r in await conn.execute_query_dict("select code, title_ko from product where code = any($1::text[])", [codes]):
            names[r["code"]] = r["title_ko"]
    orders = await conn.execute_query_dict(
        """select code, total_amount, item_name, paid_at from shop.shop_order
           where paid_at >= $1 and status = 'paid' and coalesce(test, false) = false
             and (member_id is null or not (member_id = any($2::int[])))""", [since, internal_ids])
    day_from = since.astimezone(KST).date()
    tr = await conn.execute_query_dict(
        "select kind, reason, agent, sum(hits) as n from shop.traffic_hit where day >= $1 group by 1, 2, 3", [day_from])
    kinds = Counter()
    bad_agents = Counter()
    for r in tr:
        kinds[r["kind"]] += r["n"]
        if r["kind"] == "invalid":
            bad_agents[f"{r['agent']} ({REASON_NAMES.get(r['reason'], r['reason'])})"] += r["n"]

    sess_list = []
    for s in sorted(sessions.values(), key=lambda x: x["first"]):
        sess_list.append({
            "at": s["first"].astimezone(KST).strftime("%m-%d %H:%M"),
            "source": s["src"] or "직접 방문",
            "pages": len(s["pages"]),
            "seconds": int((s["last"] - s["first"]).total_seconds()),
            "products": [names.get(c, c) for c in dict.fromkeys(s["products"])][:5],
            "cart": "add_to_cart" in s["steps"], "checkout": "begin_checkout" in s["steps"], "purchase": "purchase" in s["steps"],
            "device": s["device"], "browser": s["browser"],
        })
    sources = Counter(x["source"] for x in sess_list)
    real_visitors = len({e["visitor"] for e in real})
    outside = sum(n for k, n in sources.items() if k != "직접 방문")
    # 알릴 일: 실제로 둘러본 손님(화면 2개+ 또는 상품 조회) · 바깥(검색 · SNS) 유입 · 결제. 첫 화면 0초 이탈 한 번은 알리지 않는다
    engaged = sum(1 for x in sess_list if x["pages"] >= 2 or x["products"])
    notable = bool(engaged or orders or outside)
    return {
        "window": {"hours": hours, "from": since.astimezone(KST).strftime("%Y-%m-%d %H:%M"), "to": now.astimezone(KST).strftime("%Y-%m-%d %H:%M")},
        "notable": notable,
        "real": {"visitors": real_visitors, "sessions": len(sess_list), "engaged": engaged, "outside": outside,
                 "product_views": sum(len(x["products"]) for x in sess_list),
                 "carts": sum(x["cart"] for x in sess_list), "checkouts": sum(x["checkout"] for x in sess_list),
                 "orders": len(orders), "revenue": sum(o["total_amount"] or 0 for o in orders),
                 "sources": [{"name": k, "sessions": n} for k, n in sources.most_common()]},
        "sessions": sess_list[:20],
        "orders": [{"code": o["code"], "amount": o["total_amount"], "item": o["item_name"],
                    "at": o["paid_at"].astimezone(KST).strftime("%m-%d %H:%M")} for o in orders],
        "excluded": {"foreign": len(foreign_v), "burst_bot": len(burst_v & {e["visitor"] for e in ev}),
                     "internal": len(internal_v & {e["visitor"] for e in ev})},
        "server": {"since_day": day_from.isoformat(), "valid": kinds["valid"], "crawler": kinds["crawler"], "invalid": kinds["invalid"],
                   "top_invalid": [{"name": k, "hits": n} for k, n in bad_agents.most_common(5)]},
    }