"""자사몰 유입 요약 — 6시간마다 도는 점검 루틴용 (2026-11-18). API GET /shop-analytics/digest 와 같은 내용.

    docker exec agc_app python -m scripts.shop_digest --hours 6          # 사람이 읽는 글
    docker exec agc_app python -m scripts.shop_digest --hours 6 --json   # 원본
첫 줄이 NOTABLE 이면 알릴 일(진짜 손님 · 외부 유입 · 결제)이 있다, QUIET 이면 없다.
"""

import argparse
import asyncio
import json

from tortoise import Tortoise

from database import TORTOISE_ORM
from services import shop_analytics


def text(d: dict) -> str:
    r, w, x, s = d["real"], d["window"], d["excluded"], d["server"]
    out = [("NOTABLE" if d["notable"] else "QUIET") + f" · 자사몰 유입 {w['from']} ~ {w['to']} ({w['hours']}시간)"]
    out.append(f"진짜 손님 {r['visitors']}명 · 세션 {r['sessions']} · 상품 조회 {r['product_views']} · 장바구니 {r['carts']} · 결제 시도 {r['checkouts']} · 주문 {r['orders']}건 {r['revenue']:,}원")
    if r["sources"]:
        out.append("유입 경로: " + ", ".join(f"{a['name']} {a['sessions']}" for a in r["sources"]))
    for v in d["sessions"]:
        flags = "".join([" 담음" if v["cart"] else "", " 결제시도" if v["checkout"] else "", " 구매" if v["purchase"] else ""])
        prods = (" · " + ", ".join(v["products"])) if v["products"] else ""
        out.append(f"  - {v['at']} {v['source']} · 화면 {v['pages']} · {v['seconds']}초 · {v['device']}/{v['browser']}{prods}{flags}")
    for o in d["orders"]:
        out.append(f"  * 주문 {o['code']} {o['amount']:,}원 {o['item']} ({o['at']})")
    out.append(f"뺀 방문: 해외 {x['foreign']} · 브라우저인 척하는 봇 {x['burst_bot']} · 우리 계정 {x['internal']}")
    out.append(f"서버 요청({s['since_day']}~): 정상 {s['valid']} · 검색 봇 {s['crawler']} · 무효 {s['invalid']}"
               + ((" — " + ", ".join(f"{a['name']} {a['hits']}" for a in s["top_invalid"])) if s["top_invalid"] else ""))
    return "\n".join(out)


async def main(hours: int, as_json: bool) -> None:
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        d = await shop_analytics.digest(hours)
        print(json.dumps(d, ensure_ascii=False, indent=1) if as_json else text(d))
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=6)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.hours, a.json))