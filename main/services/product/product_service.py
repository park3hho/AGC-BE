from datetime import datetime, timezone

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.functions import Count

from models.product.price_survey import PriceSurveyOption
from models.product.pricing import ProductPricing
from models.product.product import Product
from schemas.product import ProductCreate, ProductUpdate
from services.product.price_survey_service import PriceSurveyService, alive_surveys
from services.product.serializers import money_cny, product_dict
from utils.code_gen import CODE_ISSUE_RETRIES, PRODUCT_CODE_PREFIX, next_code, today_kst


def alive_products():
    """삭제되지 않은 제품만. 코드 발급(next_code)은 삭제된 것까지 봐야 코드가 다시 쓰이지 않으므로 이걸 쓰지 않는다."""
    return Product.filter(deleted_at=None)


async def _list_extras(product_ids: list[int]) -> dict[int, dict]:
    """목록 행에 붙이는 값 — 최근 가격 조사의 옵션 수·최저가, 가격을 저장한 판매처.
    페이지에 나온 제품만 재므로 쿼리 3번으로 끝낸다 (제품마다 따로 읽지 않는다)."""
    extras = {pid: {"latest_survey": None, "priced_platforms": [], "shipping_unknown": 0} for pid in product_ids}
    if not product_ids:
        return extras

    # 제품별 최근 조사 (조사일 최근 → id 큰 순 첫 번째)
    surveys = await (
        alive_surveys().filter(product_id__in=product_ids)
        .order_by("-survey_date", "-id").values("id", "product_id", "code", "survey_date")
    )
    latest = {}
    for s in surveys:
        latest.setdefault(s["product_id"], s)

    prices: dict[int, list] = {}
    unknown: dict[int, int] = {}      # 최근 조사에서 용량을 못 읽어 배송비를 모르는 옵션 수 (2026-10-30)
    from services.pricing.shipping_service import option_shipping   # 순환 import 방지
    cats = {r["id"]: r["category"] for r in await Product.filter(id__in=product_ids).values("id", "category")}
    sid_pid = {s["id"]: pid for pid, s in latest.items()}
    for o in await PriceSurveyOption.filter(survey_id__in=[s["id"] for s in latest.values()]).values(
        "survey_id", "price_cny", "option1", "option2"
    ):
        prices.setdefault(o["survey_id"], []).append(o["price_cny"])
        cat = cats.get(sid_pid.get(o["survey_id"])) or "beverage"
        if option_shipping(o["option1"], o["option2"], cat)["shipping_cny"] is None:
            unknown[o["survey_id"]] = unknown.get(o["survey_id"], 0) + 1

    for pid, s in latest.items():
        ps = prices.get(s["id"], [])
        extras[pid]["latest_survey"] = {
            "id": s["id"],
            "code": s["code"],
            "survey_date": s["survey_date"].isoformat(),
            "option_count": len(ps),
            "min_price_cny": money_cny(min(ps)) if ps else None,
        }
        extras[pid]["shipping_unknown"] = unknown.get(s["id"], 0)   # 0 보다 크면 가격 책정 '배송비 모름' (완료로 안 침)

    for r in await ProductPricing.filter(product_id__in=product_ids).values("product_id", "platform"):
        platform = r["platform"]
        extras[r["product_id"]]["priced_platforms"].append(getattr(platform, "value", platform))

    # 채택한 묶음 중 판매가가 빈 판매처 칸 수 (판매처 2곳 × 묶음) — 가격 책정 목록에서 "묶음 판매가 필요" 로 보인다
    from core.pricing_config import MARKET_PLATFORMS
    from models.product.pricing import OptionPrice, ProductBundle   # 순환 import 방지
    for pid in product_ids:
        extras[pid]["bundle_unpriced"] = 0
    adopted = await ProductBundle.filter(product_id__in=product_ids, deleted_at=None).values(
        "product_id", "option_id", "bundle_qty"
    )
    if adopted:
        priced = {
            (r["option_id"], r["bundle_qty"], getattr(r["pricing__platform"], "value", r["pricing__platform"]))
            for r in await OptionPrice.filter(
                option_id__in=[a["option_id"] for a in adopted], bundle_qty__gt=1
            ).values("option_id", "bundle_qty", "pricing__platform")
        }
        for a in adopted:
            for pf in MARKET_PLATFORMS:      # 자사몰 묶음가는 세지 않는다
                if (a["option_id"], a["bundle_qty"], pf.value) not in priced:
                    extras[a["product_id"]]["bundle_unpriced"] += 1
    return extras


async def _get_alive(product_id: int) -> Product:
    p = await alive_products().get_or_none(id=product_id)
    if not p:
        raise HTTPException(status_code=404, detail="제품을 찾을 수 없습니다.")
    return p


class ProductService:
    @staticmethod
    async def next_code() -> str:
        """다음에 발급될 제품 코드 미리보기 — 실제 발급은 create 시점 (그 사이 다른 등록이 있으면 달라진다)."""
        return await next_code(Product, PRODUCT_CODE_PREFIX, today_kst())

    @staticmethod
    async def create(body: ProductCreate) -> dict:
        for _ in range(CODE_ISSUE_RETRIES):
            code = await next_code(Product, PRODUCT_CODE_PREFIX, today_kst())
            try:
                p = await Product.create(code=code, **body.model_dump())
                return product_dict(p)
            except IntegrityError:
                continue    # 같은 번호를 다른 요청이 먼저 가져감 → 다음 번호로 다시
        raise HTTPException(status_code=409, detail="제품 코드 발급이 겹쳤습니다. 다시 시도해주세요.")

    @staticmethod
    async def list(q: str | None, page: int, size: int, category: str | None = None, subcategory: str | None = None) -> dict:
        qs = alive_products()
        if category:
            qs = qs.filter(category=category)
        if subcategory:
            qs = qs.filter(subcategory=None if subcategory == "none" else subcategory)  # none = 소분류 안 정한 것
        if q:
            qs = qs.filter(Q(code__icontains=q) | Q(title_cn__icontains=q) | Q(title_ko__icontains=q))
        total = await qs.count()
        rows = (
            await qs.annotate(survey_count=Count("price_surveys", _filter=Q(price_surveys__deleted_at=None)))
            .order_by("-created_at", "-id")
            .offset((page - 1) * size)
            .limit(size)
        )
        extras = await _list_extras([p.id for p in rows])
        items = [{**product_dict(p), "survey_count": p.survey_count, **extras[p.id]} for p in rows]
        return {"items": items, "total": total, "page": page, "size": size}

    @staticmethod
    async def get(product_id: int) -> dict:
        p = await _get_alive(product_id)
        surveys = await PriceSurveyService.summaries(product_id=p.id)
        return {"product": product_dict(p), "price_surveys": surveys}

    @staticmethod
    async def update(product_id: int, body: ProductUpdate) -> dict:
        data = body.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        p = await _get_alive(product_id)
        await p.update_from_dict(data).save()
        return product_dict(p)

    @staticmethod
    async def delete(product_id: int) -> None:
        p = await _get_alive(product_id)
        p.deleted_at = datetime.now(timezone.utc)
        await p.save(update_fields=["deleted_at", "updated_at"])
