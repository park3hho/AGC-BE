"""옵션별 실측 기록 — 30분 점검 루틴용 (2026-11-18). API POST /option-measures 와 같은 동작.

    # 집운 결제를 기록할 때, 집운 창고가 잰 상자 무게·크기를 같이 넣는다
    docker exec agc_app python -m scripts.measure_record --jiyun LP00851561428901 --weight 8.35 --l 40 --w 30 --h 25
    docker exec agc_app python -m scripts.measure_record --order OR-261116-0009 --weight 11.2 --l 45 --w 32 --h 28
    # 합포장이면 자동으로 mixed (평균에서 빠짐). 강제로 지정: --mixed / --not-mixed
    # 보기
    docker exec agc_app python -m scripts.measure_record --list --product 442
    # 예전 집운 기록 무게만 채우기 (먼저 --dry 로 확인)
    docker exec agc_app python -m scripts.measure_record --backfill --dry
    docker exec agc_app python -m scripts.measure_record --backfill
비공개 데이터 — 출력에 개인정보 없음 (주문 코드 · SKU · 무게 · 크기만).
"""

import argparse
import asyncio
import json

from tortoise import Tortoise

from database import TORTOISE_ORM
from services.order.measure_service import MeasureService


async def main(a):
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        if a.backfill:
            out = await MeasureService.backfill(dry=a.dry)
        elif a.list:
            out = await MeasureService.list(product_id=a.product, option_id=a.option)
        else:
            mixed = True if a.mixed else (False if a.not_mixed else None)
            out = await MeasureService.record(order_code=a.order, jiyun_no=a.jiyun, weight_kg=a.weight, length_cm=a.l,
                                              width_cm=a.w, height_cm=a.h, source=a.source, mixed=mixed, memo=a.memo)
        print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--order"); p.add_argument("--jiyun")
    p.add_argument("--weight", type=float); p.add_argument("--l", type=float); p.add_argument("--w", type=float); p.add_argument("--h", type=float)
    p.add_argument("--source", default="jiyun"); p.add_argument("--memo")
    p.add_argument("--mixed", action="store_true"); p.add_argument("--not-mixed", action="store_true")
    p.add_argument("--list", action="store_true"); p.add_argument("--product", type=int); p.add_argument("--option", type=int)
    p.add_argument("--backfill", action="store_true"); p.add_argument("--dry", action="store_true")
    asyncio.run(main(p.parse_args()))
