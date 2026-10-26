from datetime import datetime, timezone

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.functions import Count, Max, Min
from tortoise.transactions import in_transaction

from models.product.price_survey import PriceSurvey, PriceSurveyOption
from models.product.product import Product
from schemas.price_survey import PriceSurveyCreate, PriceSurveyOptionPatch, PriceSurveyUpdate
from services.product.serializers import survey_detail_dict, survey_summary_dict
from utils.code_gen import CODE_ISSUE_RETRIES, SURVEY_CODE_PREFIX, next_code


def alive_surveys():
    """삭제되지 않은 조사 중 제품도 삭제되지 않은 것만 (제품을 지우면 그 조사도 목록에서 사라진다).
    코드 발급(next_code)은 삭제된 것까지 봐야 하므로 이걸 쓰지 않는다."""
    return PriceSurvey.filter(deleted_at=None, product__deleted_at=None)


def _with_option_stats(qs):
    # select_related 를 쓰면 product 컬럼이 GROUP BY 에 안 들어가 Postgres 가 거부한다
    #   → 제품은 prefetch_related 로 따로 한 번 더 읽는다
    return qs.annotate(
        option_count=Count("options"),
        min_price=Min("options__price_cny"),
        max_price=Max("options__price_cny"),
    ).prefetch_related("product")


async def _get_alive(survey_id: int) -> PriceSurvey:
    s = await alive_surveys().get_or_none(id=survey_id).select_related("product")
    if not s:
        raise HTTPException(status_code=404, detail="가격 조사를 찾을 수 없습니다.")
    return s


class PriceSurveyService:
    @staticmethod
    async def next_code(survey_date) -> str:
        """조사일 기준 다음 조사 코드번호 미리보기 — 실제 발급은 create 시점."""
        return await next_code(PriceSurvey, SURVEY_CODE_PREFIX, survey_date)

    @staticmethod
    async def create(body: PriceSurveyCreate) -> dict:
        product = await Product.get_or_none(code=body.product_code, deleted_at=None)
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
        s = await _get_alive(survey_id)
        options = await PriceSurveyOption.filter(survey_id=s.id).order_by("id")
        return survey_detail_dict(s, options)

    @staticmethod
    async def list(product_code: str | None, page: int, size: int) -> dict:
        qs = alive_surveys()
        if product_code:
            qs = qs.filter(product__code=product_code)
        total = await qs.count()
        rows = await _with_option_stats(qs).order_by("-survey_date", "-id").offset((page - 1) * size).limit(size)
        return {"items": [survey_summary_dict(s) for s in rows], "total": total, "page": page, "size": size}

    @staticmethod
    async def summaries(product_id: int) -> list[dict]:
        """제품 상세에 붙이는 조사 요약 목록 (조사일 최근 순)."""
        rows = await _with_option_stats(alive_surveys().filter(product_id=product_id)).order_by("-survey_date", "-id")
        return [survey_summary_dict(s) for s in rows]

    @staticmethod
    async def update(survey_id: int, body: PriceSurveyUpdate) -> dict:
        data = body.model_dump(exclude_unset=True, exclude={"options"})
        if not data and "options" not in body.model_fields_set:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        s = await _get_alive(survey_id)
        # 조사 필드 + 옵션 전체 교체는 전부 저장되거나 전부 안 되거나
        async with in_transaction() as conn:
            if data:
                await s.update_from_dict(data).save(using_db=conn)
            if body.options is not None:
                await PriceSurveyOption.filter(survey_id=s.id).using_db(conn).delete()
                await PriceSurveyOption.bulk_create(
                    [PriceSurveyOption(survey_id=s.id, **o.model_dump()) for o in body.options],
                    using_db=conn,
                )
        return await PriceSurveyService.get(s.id)

    @staticmethod
    async def patch_option(survey_id: int, option_id: int, body: PriceSurveyOptionPatch) -> dict:
        """옵션 1개를 제자리에서 수정 — id·price_cny 는 그대로라 저장된 판매가와 마켓 등록 연결이 유지된다."""
        data = body.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        s = await _get_alive(survey_id)
        opt = await PriceSurveyOption.get_or_none(id=option_id, survey_id=s.id)
        if not opt:
            raise HTTPException(status_code=404, detail="옵션을 찾을 수 없습니다.")
        new_key = (data.get("option1", opt.option1), data.get("option2", opt.option2))
        dup = await PriceSurveyOption.filter(
            survey_id=s.id, option1=new_key[0], option2=new_key[1]
        ).exclude(id=opt.id).exists()
        if dup:
            raise HTTPException(status_code=409, detail=f"같은 옵션이 이미 있습니다: {new_key[0]} / {new_key[1] or '-'}")
        await opt.update_from_dict(data).save(update_fields=[*data.keys(), "updated_at"])
        return await PriceSurveyService.get(s.id)

    @staticmethod
    async def delete(survey_id: int) -> None:
        s = await _get_alive(survey_id)
        s.deleted_at = datetime.now(timezone.utc)
        await s.save(update_fields=["deleted_at", "updated_at"])
