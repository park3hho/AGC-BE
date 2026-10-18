from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.functions import Count, Max, Min
from tortoise.transactions import in_transaction

from models.product.price_survey import PriceSurvey, PriceSurveyOption
from models.product.product import Product
from schemas.price_survey import PriceSurveyCreate
from services.product.serializers import survey_detail_dict, survey_summary_dict
from utils.code_gen import CODE_ISSUE_RETRIES, SURVEY_CODE_PREFIX, next_code


def _with_option_stats(qs):
    # select_related 를 쓰면 product 컬럼이 GROUP BY 에 안 들어가 Postgres 가 거부한다
    #   → 제품은 prefetch_related 로 따로 한 번 더 읽는다
    return qs.annotate(
        option_count=Count("options"),
        min_price=Min("options__price_cny"),
        max_price=Max("options__price_cny"),
    ).prefetch_related("product")


class PriceSurveyService:
    @staticmethod
    async def next_code(survey_date) -> str:
        """조사일 기준 다음 조사 코드번호 미리보기 — 실제 발급은 create 시점."""
        return await next_code(PriceSurvey, SURVEY_CODE_PREFIX, survey_date)

    @staticmethod
    async def create(body: PriceSurveyCreate) -> dict:
        product = await Product.get_or_none(code=body.product_code)
        if not product:
            raise HTTPException(status_code=404, detail=f"등록되지 않은 제품 코드입니다: {body.product_code}")

        data = body.model_dump(exclude={"product_code", "options"})
        for _ in range(CODE_ISSUE_RETRIES):
            code = await next_code(PriceSurvey, SURVEY_CODE_PREFIX, body.survey_date)
            try:
                # 조사 + 옵션은 전부 저장되거나 전부 안 되거나
                async with in_transaction() as conn:
                    survey = await PriceSurvey.create(product=product, code=code, using_db=conn, **data)
                    await PriceSurveyOption.bulk_create(
                        [PriceSurveyOption(survey=survey, **o.model_dump()) for o in body.options],
                        using_db=conn,
                    )
                return await PriceSurveyService.get(survey.id)
            except IntegrityError:
                continue    # 같은 번호를 다른 요청이 먼저 가져감 → 롤백 후 다음 번호로 다시
        raise HTTPException(status_code=409, detail="조사 코드번호 발급이 겹쳤습니다. 다시 시도해주세요.")

    @staticmethod
    async def get(survey_id: int) -> dict:
        s = await PriceSurvey.get_or_none(id=survey_id).select_related("product")
        if not s:
            raise HTTPException(status_code=404, detail="가격 조사를 찾을 수 없습니다.")
        options = await PriceSurveyOption.filter(survey_id=s.id).order_by("id")
        return survey_detail_dict(s, options)

    @staticmethod
    async def list(product_code: str | None, page: int, size: int) -> dict:
        qs = PriceSurvey.all()
        if product_code:
            qs = qs.filter(product__code=product_code)
        total = await qs.count()
        rows = await _with_option_stats(qs).order_by("-survey_date", "-id").offset((page - 1) * size).limit(size)
        return {"items": [survey_summary_dict(s) for s in rows], "total": total, "page": page, "size": size}

    @staticmethod
    async def summaries(product_id: int) -> list[dict]:
        """제품 상세에 붙이는 조사 요약 목록 (조사일 최근 순)."""
        rows = await _with_option_stats(PriceSurvey.filter(product_id=product_id)).order_by("-survey_date", "-id")
        return [survey_summary_dict(s) for s in rows]
