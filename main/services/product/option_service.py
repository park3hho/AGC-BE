"""제품 옵션 (product_option) — 제품 단위 고정 옵션 (2026-11-18 옵션 구조 정규화).

- 옵션 id 는 바뀌지 않는다. 가격 조사를 새로 하거나 옵션 목록을 통째로 보내도 같은 (옵션1, 옵션2)는 같은 id 를 다시 쓴다.
  비교는 공백을 빼고 소문자로 (norm_key). 정말 새 조합만 새 id 를 만든다.
- 조사별 가격은 price_survey_price (관찰 기록). product_option.price_cny 는 '현재 원가' = 살아 있는 조사 중
  최근 조사(조사일 → id 큰 순)의 값이며 refresh_current_prices 만 고친다.
- 지우기는 소프트 삭제: deleted_at + 그 옵션의 판매가(option_price) 삭제 + 대표 옵션 지정 해제 + 묶음 채택 해제 +
  경쟁가 옵션 비움 (예전 하드 삭제 때 CASCADE / SET NULL 로 일어나던 일과 같다). id 는 남아 옛 주문 SKU 를 계속 찾는다.
"""

import re
from types import SimpleNamespace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from models.product.price_survey import PriceSurveyPrice, ProductOption
from utils.option_spec import spec_fields


def norm_key(option1: Optional[str], option2: Optional[str]) -> tuple[str, str]:
    """같은 옵션인지 비교하는 키 — 공백 전부 빼고 소문자 ("500 ML" == "500ml")."""
    def n(v):
        return re.sub(r"\s+", "", v or "").lower()
    return n(option1), n(option2)


def alive_options(product_id: int):
    """제품의 지금 옵션 (지운 것 빼고) — 보이는 순서 = sort → id."""
    return ProductOption.filter(product_id=product_id, deleted_at=None).order_by("sort", "id")


async def match_options(product_id: int, items: list, conn, rename: bool = False) -> list[tuple[ProductOption, Decimal]]:
    """조사에 들어온 옵션들(PriceSurveyOptionIn)을 제품 옵션에 맞춘다 → [(제품 옵션, 이번 조사 가격)].
    같은 키의 옵션이 있으면 그 줄을 제자리에서 고친다 (보낸 사진/바코드, 지웠던 것은 살린다).
    이름 표기(공백·대소문자 차이)는 rename=True(조사 옵션 목록 수정)일 때만 보낸 대로 바꾼다 —
    새 조사·옵션 추가는 검수된 기존 표기를 그대로 둔다.
    없으면 새로 만든다. 사진·바코드는 보낸 값이 있을 때만 바꾼다 (비워 보내도 기존 값을 지우지 않는다)."""
    existing = await ProductOption.filter(product_id=product_id).using_db(conn).order_by("id")
    by_key: dict[tuple, ProductOption] = {}
    for o in existing:      # 같은 키가 여럿이면 살아 있는 것 → id 작은 것
        k = norm_key(o.option1, o.option2)
        cur = by_key.get(k)
        if cur is None or (cur.deleted_at is not None and o.deleted_at is None):
            by_key[k] = o
    next_sort = max((o.sort for o in existing), default=0)
    out = []
    for it in items:
        d = it.model_dump()
        price = d.pop("price_cny")
        o = by_key.get(norm_key(d["option1"], d.get("option2")))
        if o is None:
            next_sort += 1
            o = await ProductOption.create(product_id=product_id, price_cny=price, sort=next_sort, using_db=conn,
                                           option1=d["option1"], option2=d.get("option2"),
                                           photo_url=d.get("photo_url"), barcode=d.get("barcode"),
                                           **spec_fields(d.get("option2")))   # 규격 구조 칸 자동 해석 (2026-11-22)
            by_key[norm_key(o.option1, o.option2)] = o
        else:
            changed = []
            for f in ("option1", "option2") if rename else ():
                if getattr(o, f) != d.get(f):
                    setattr(o, f, d.get(f))
                    changed.append(f)
            if "option2" in changed and o.spec_source != "manual":   # 규격 글자가 바뀌면 구조 칸도 다시 해석
                for k, v in spec_fields(o.option2).items():
                    setattr(o, k, v)
                    changed.append(k)
            for f in ("photo_url", "barcode"):
                if d.get(f) is not None and getattr(o, f) != d.get(f):
                    setattr(o, f, d.get(f))
                    changed.append(f)
            if o.deleted_at is not None:
                o.deleted_at = None
                changed.append("deleted_at")
            if changed:
                await o.save(using_db=conn, update_fields=[*changed, "updated_at"])
        out.append((o, price))
    return out


async def record_prices(survey_id: int, pairs: list[tuple[ProductOption, Decimal]], conn) -> None:
    """이 조사의 관찰 가격을 넣거나 고친다 (같은 조사 · 같은 옵션은 1줄)."""
    have = {r.option_id: r for r in await PriceSurveyPrice.filter(survey_id=survey_id).using_db(conn)}
    for o, price in pairs:
        r = have.get(o.id)
        if r is None:
            await PriceSurveyPrice.create(survey_id=survey_id, option_id=o.id, price_cny=price, using_db=conn)
        elif Decimal(str(r.price_cny)) != Decimal(str(price)):
            r.price_cny = price
            await r.save(using_db=conn, update_fields=["price_cny", "updated_at"])


async def refresh_current_prices(product_id: int, conn, reason: str = "가격조사 반영") -> None:
    """product_option.price_cny = 살아 있는 조사 중 최근 조사(조사일 → id 큰 순)에서 본 값. 본 적 없으면 그대로.
    바뀐 옵션은 매입가 이력(option_cost_log, source=manual, 이전 → 새)에 남긴다 (2026-11-27)."""
    q = "select id, price_cny from product_option where product_id = $1"
    before = {r["id"]: r["price_cny"] for r in await conn.execute_query_dict(q, [product_id])}
    await conn.execute_query(
        """
        update product_option o set price_cny = x.price_cny, updated_at = now()
        from (
          select distinct on (p.option_id) p.option_id, p.price_cny
          from price_survey_price p join price_survey s on s.id = p.survey_id
          where s.product_id = $1 and s.deleted_at is null
          order by p.option_id, s.survey_date desc, s.id desc
        ) x
        where o.id = x.option_id and o.product_id = $1 and o.price_cny is distinct from x.price_cny
        """,
        [product_id],
    )
    after = {r["id"]: r["price_cny"] for r in await conn.execute_query_dict(q, [product_id])}
    if any(before.get(k) != v for k, v in after.items()):
        try:
            from services.order.cost_sync import log_manual_changes
            await log_manual_changes(before, after, reason)
        except Exception:
            pass


async def used_by_listings(product_id: int, option_ids: set[int]) -> list[str]:
    """살아 있는 마켓 등록(items[].option_id)이 쓰는 옵션이면 '판매처 마켓상품번호' 목록."""
    from models.product.listing import MarketListing  # 순환 import 피함

    ids = {str(i) for i in option_ids}
    return [
        f"{getattr(l.platform, 'value', l.platform)} {l.market_product_id}"
        for l in await MarketListing.filter(product_id=product_id, deleted_at=None)
        if any(str(it.get("option_id")) in ids for it in (l.items or []))
    ]


async def soft_delete(option_ids: list[int], conn) -> None:
    """옵션 소프트 삭제 + 예전 하드 삭제 때 따라 지워지던 것들 정리 (모듈 설명 참고)."""
    if not option_ids:
        return
    from models.product.competitor import CompetitorPrice
    from models.product.pricing import OptionPrice, ProductBundle, ProductPricing

    now = datetime.now(timezone.utc)
    await ProductOption.filter(id__in=option_ids, deleted_at=None).using_db(conn).update(deleted_at=now, updated_at=now)
    await OptionPrice.filter(option_id__in=option_ids).using_db(conn).delete()
    await ProductPricing.filter(base_option_id__in=option_ids).using_db(conn).update(base_option_id=None)
    await ProductBundle.filter(option_id__in=option_ids, deleted_at=None).using_db(conn).update(deleted_at=now)
    await CompetitorPrice.filter(option_id__in=option_ids).using_db(conn).update(option_id=None)


SPEC_ATTRS = ("unit_amount", "unit", "unit_count", "count_word", "pack_count", "total_count",
              "spec_note", "spec_checked", "spec_source")


async def survey_options(survey_id: int) -> list[SimpleNamespace]:
    """조사 1건의 옵션 = 그 조사에서 본 가격 + 제품 옵션 정보 (지운 옵션은 뺀다). 응답 모양은 예전 그대로."""
    rows = await PriceSurveyPrice.filter(survey_id=survey_id, option__deleted_at=None).select_related("option")
    rows.sort(key=lambda r: (r.option.sort, r.option.id))
    return [
        SimpleNamespace(id=r.option.id, option1=r.option.option1, option2=r.option.option2, price_cny=r.price_cny,
                        photo_url=r.option.photo_url, barcode=r.option.barcode,
                        **{k: getattr(r.option, k) for k in SPEC_ATTRS})
        for r in rows
    ]
