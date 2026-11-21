"""제품 배송비 방식 자동 분류 (2026-11-20 사용자 · Manager 전달).

음료(category beverage)는 무게와 상관없이 항상 included (2026-11-21 사용자) — 아래 300g 규칙은 음료가 아닌 제품(tea · other)에만.
낱개 계산 무게 = max(실무게 − 상자, 부피무게) ÷ 개수 — 대표 옵션 기준.
  300g 이상 → included(배송비 포함형, 지금 방식) · 미만 → separate(배송비 별도형, 마트형).
대표 옵션 = 가격 책정 기준 옵션(쿠팡 → 네이버) · 없으면 첫 옵션.
개수나 무게를 못 읽으면(용량 없음 → 최소 상자 가정 등) null — 사람이 정한다.
사람이 고른 값(shipping_mode_source='manual')은 자동이 덮어쓰지 않는다."""

import logging
import re
from decimal import Decimal
from typing import Optional

from core.shipping_config import BOX_WEIGHT_G
from models.product.price_survey import ProductOption
from models.product.pricing import ProductPricing
from models.product.product import Product
from utils.volume import _COUNT_UNIT, _TIMES, _VOLUME

logger = logging.getLogger(__name__)
THRESHOLD_G = 300
MODES = ("included", "separate")
# 개수 단위 — utils/volume 보다 넓게 (봉 · 개입 · 갑 · 포 · 袋 · 包 …)
_COUNT_WIDE = re.compile(r"(\d+)\s*(개입|팩|개|병|캔|입|봉|갑|포|정|매|통|박스|盒|瓶|罐|支|袋|听|包|片|枚|条|箱)")


def unit_count(option1: Optional[str], option2: Optional[str]) -> Optional[int]:
    """옵션 이름의 개수 — '500ml×15병' → 15, '70g×10봉' → 10, '1.5L' → 1, 용량도 개수도 없으면 None."""
    for text in (option2, option1):
        if not text:
            continue
        m = _VOLUME.search(text)
        if m:
            rest = text[m.end():]
            t = _TIMES.match(rest)
            if t:
                return int(t.group(1))
            u = _COUNT_UNIT.search(rest) or _COUNT_WIDE.search(rest)
            return int(u.group(1)) if u else 1
        u = _COUNT_WIDE.search(text)
        if u:
            return int(u.group(1))
    return None


async def _rep_option(p: Product) -> Optional[ProductOption]:
    for plat in ("coupang", "naver"):
        pr = await ProductPricing.filter(product_id=p.id, platform=plat).select_related("base_option").first()
        o = getattr(pr, "base_option", None) if pr else None
        if o and o.deleted_at is None:
            return o
    return await ProductOption.filter(product_id=p.id, deleted_at=None).order_by("sort", "id").first()


async def classify(p: Product) -> dict:
    """{mode, unit_weight_g, unit_count, note} — 못 정하면 mode None."""
    from services.pricing.shipping_service import option_shipping
    o = await _rep_option(p)
    if not o:
        return {"mode": None, "unit_weight_g": None, "unit_count": None, "note": "옵션 없음"}
    label = " ".join(x for x in (o.option1, o.option2) if x)[:80]
    sh = option_shipping(o.option1, o.option2, p.category or "beverage")
    n = unit_count(o.option1, o.option2)
    bev = (p.category or "beverage") == "beverage"
    if sh.get("box_assumed") or (sh.get("weight_g") is None and sh.get("dim_weight_g") is None):
        if bev:
            return {"mode": "included", "unit_weight_g": None, "unit_count": n, "note": f"{label} · 용량을 못 읽음 · 음료는 포함형 고정"}
        return {"mode": None, "unit_weight_g": None, "unit_count": n, "note": f"{label} · 용량·무게를 못 읽음"}
    if not n:
        if bev:
            return {"mode": "included", "unit_weight_g": None, "unit_count": None, "note": f"{label} · 개수를 못 읽음 · 음료는 포함형 고정"}
        return {"mode": None, "unit_weight_g": None, "unit_count": None, "note": f"{label} · 개수를 못 읽음"}
    actual = (sh["weight_g"] - BOX_WEIGHT_G) if sh.get("weight_g") is not None else 0
    dim = sh.get("dim_weight_g") or 0
    total = max(actual, dim)
    unit = int(round(Decimal(total) / n))
    basis = "부피무게" if dim > actual else "무게"
    note = f"{label} · {basis} {total:,}g ÷ {n} = {unit}g"
    if (p.category or "beverage") == "beverage":   # 음료는 무게와 상관없이 포함형 (사용자 11-21)
        return {"mode": "included", "unit_weight_g": unit, "unit_count": n, "note": f"{note} · 음료는 포함형 고정"[:200]}
    mode = "included" if unit >= THRESHOLD_G else "separate"
    return {"mode": mode, "unit_weight_g": unit, "unit_count": n, "note": note[:200]}


async def sync_product(product_id: int) -> Optional[dict]:
    """자동 분류를 다시 계산해 저장 (manual 이면 낱개 무게·근거만 갱신, 방식은 그대로)."""
    p = await Product.get_or_none(id=product_id, deleted_at=None)
    if not p:
        return None
    try:
        r = await classify(p)
    except Exception as e:
        logger.warning(f"배송비 방식 분류 실패 product={product_id}: {e!r}")
        return None
    vals = {"unit_weight_g": r["unit_weight_g"], "unit_count": r["unit_count"], "shipping_mode_note": r["note"]}
    if p.shipping_mode_source != "manual":
        vals["shipping_mode"] = r["mode"]
    if any(getattr(p, k) != v for k, v in vals.items()):
        await Product.filter(id=p.id).update(**vals)
    return r


async def sync_all() -> dict:
    out = {"included": 0, "separate": 0, "none": 0, "manual": 0}
    for pid in await Product.filter(deleted_at=None).values_list("id", flat=True):
        await sync_product(pid)
    for p in await Product.filter(deleted_at=None):
        if p.shipping_mode_source == "manual":
            out["manual"] += 1
        out[p.shipping_mode or "none"] += 1
    return out


def kick(product_id: int) -> None:
    """옵션·조사·분류가 바뀐 직후 — 기다리지 않고 뒤에서."""
    import asyncio
    try:
        asyncio.get_running_loop().create_task(sync_product(product_id))
    except RuntimeError:
        pass
