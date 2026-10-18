from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.functions import Count

from models.product.product import Product
from schemas.product import ProductCreate
from services.product.price_survey_service import PriceSurveyService
from services.product.serializers import product_dict
from utils.code_gen import CODE_ISSUE_RETRIES, PRODUCT_CODE_PREFIX, next_code, today_kst


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
    async def list(q: str | None, page: int, size: int) -> dict:
        qs = Product.all()
        if q:
            qs = qs.filter(Q(code__icontains=q) | Q(title_cn__icontains=q) | Q(title_ko__icontains=q))
        total = await qs.count()
        rows = (
            await qs.annotate(survey_count=Count("price_surveys"))
            .order_by("-created_at", "-id")
            .offset((page - 1) * size)
            .limit(size)
        )
        items = [{**product_dict(p), "survey_count": p.survey_count} for p in rows]
        return {"items": items, "total": total, "page": page, "size": size}

    @staticmethod
    async def get(product_id: int) -> dict:
        p = await Product.get_or_none(id=product_id)
        if not p:
            raise HTTPException(status_code=404, detail="제품을 찾을 수 없습니다.")
        surveys = await PriceSurveyService.summaries(product_id=p.id)
        return {"product": product_dict(p), "price_surveys": surveys}
