from datetime import datetime, timezone

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.functions import Count, Max, Min
from tortoise.transactions import in_transaction

from models.product.price_survey import PriceSurvey, PriceSurveyPrice, ProductOption
from models.product.product import Product
from schemas.price_survey import PriceSurveyCreate, PriceSurveyOptionPatch, PriceSurveyUpdate
from services.product.option_service import (
    match_options,
    norm_key,
    record_prices,
    refresh_current_prices,
    soft_delete,
    survey_options,
    used_by_listings,
)
from services.product.serializers import survey_detail_dict, survey_summary_dict
from utils.code_gen import CODE_ISSUE_RETRIES, SURVEY_CODE_PREFIX, next_code
from utils.option_spec import spec_fields

SPEC_EDIT = ("unit_amount", "unit", "unit_count", "count_word", "pack_count", "total_count", "spec_note")


def _spec_patch(opt, data: dict) -> dict:
    """옵션 PATCH 의 규격 구조 칸 처리 (2026-11-22).
    - 구조 칸을 보내면 사람이 고친 것 → spec_source='manual', spec_checked=true. total_count 를 안 보내면 unit_count × pack_count.
    - spec_source='auto' 를 보내거나, option2 가 바뀌었는데 manual 이 아니면 → option2 로 다시 자동 해석."""
    edited = [k for k in SPEC_EDIT if k in data]
    if edited:
        if "pack_count" in data and data["pack_count"] is None:
            data["pack_count"] = 1
        if "total_count" not in data and ("unit_count" in data or "pack_count" in data):
            uc = data.get("unit_count", opt.unit_count)
            data["total_count"] = uc * (data.get("pack_count", opt.pack_count) or 1) if uc else None
        data["spec_source"] = "manual"
        data.setdefault("spec_checked", True)
        return data
    source = data.get("spec_source", opt.spec_source)
    reparse = data.get("spec_source") == "auto" or (
        "option2" in data and data["option2"] != opt.option2 and source != "manual")
    if reparse:
        checked = data.get("spec_checked", False)
        data.update(spec_fields(data.get("option2", opt.option2)))
        data["spec_checked"] = checked
    return data


def alive_surveys():
    """삭제되지 않은 조사 중 제품도 삭제되지 않은 것만 (제품을 지우면 그 조사도 목록에서 사라진다).
    코드 발급(next_code)은 삭제된 것까지 봐야 하므로 이걸 쓰지 않는다."""
    return PriceSurvey.filter(deleted_at=None, product__deleted_at=None)


def _with_option_stats(qs):
    # select_related 를 쓰면 product 컬럼이 GROUP BY 에 안 들어가 Postgres 가 거부한다
    #   → 제품은 prefetch_related 로 따로 한 번 더 읽는다
    return qs.annotate(
        option_count=Count("observations"),
        min_price=Min("observations__price_cny"),
        max_price=Max("observations__price_cny"),
    ).prefetch_related("product")


async def _get_alive(survey_id: int) -> PriceSurvey:
    s = await alive_surveys().get_or_none(id=survey_id).select_related("product")
    if not s:
        raise HTTPException(status_code=404, detail="가격 조사를 찾을 수 없습니다.")
    return s


class PriceSurveyService:
    """가격 조사 = 그날 본 옵션별 가격 기록. 옵션 자체(이름·사진·바코드·id)는 제품 옵션(product_option)이고
    조사는 price_survey_price 에 가격만 남긴다 (2026-11-18 옵션 구조 정규화, services/product/option_service)."""

    @staticmethod
    async def next_code(survey_date) -> str:
        """조사일 기준 다음 조사 코드번호 미리보기 — 실제 발급은 create 시점."""
        return await next_code(PriceSurvey, SURVEY_CODE_PREFIX, survey_date)

    @staticmethod
    async def create(body: PriceSurveyCreate) -> dict:
        """새 조사. 옵션은 제품 옵션에 맞춘다 — 같은 (옵션1, 옵션2)면 기존 id 를 그대로 쓰고 새 조합만 새로 만든다.
        이번 조사에 없는 기존 옵션은 지우지 않는다 (빼려면 옵션 삭제)."""
        product = await Product.get_or_none(code=body.product_code, deleted_at=None)
        if not product:
            raise HTTPException(status_code=404, detail=f"등록되지 않은 제품 코드입니다: {body.product_code}")

        data = body.model_dump(exclude={"product_code", "options"})
        for _ in range(CODE_ISSUE_RETRIES):
            code = await next_code(PriceSurvey, SURVEY_CODE_PREFIX, body.survey_date)
            try:
                # 조사 + 옵션 + 가격은 전부 저장되거나 전부 안 되거나
                async with in_transaction() as conn:
                    survey = await PriceSurvey.create(product=product, code=code, using_db=conn, **data)
                    pairs = await match_options(product.id, body.options, conn)
                    await record_prices(survey.id, pairs, conn)
                    await refresh_current_prices(product.id, conn)
                __import__("services.product.shipping_mode", fromlist=["kick"]).kick(product.id)   # 배송비 방식 다시 분류
                return await PriceSurveyService.get(survey.id)
            except IntegrityError:
                continue    # 같은 번호를 다른 요청이 먼저 가져감 → 롤백 후 다음 번호로 다시
        raise HTTPException(status_code=409, detail="조사 코드번호 발급이 겹쳤습니다. 다시 시도해주세요.")

    @staticmethod
    async def get(survey_id: int) -> dict:
        s = await _get_alive(survey_id)
        return survey_detail_dict(s, await survey_options(s.id))

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
        """보낸 필드만 바꾼다. options 를 보내면 이 조사의 옵션 목록을 그것으로 맞춘다:
        같은 (옵션1, 옵션2)는 id 를 유지한 채 가격·표기만 고치고, 빠진 옵션은 지운다(소프트) —
        빠진 옵션을 살아 있는 마켓 등록이 쓰면 409 (이름만 고칠 때는 PATCH options/{option_id})."""
        data = body.model_dump(exclude_unset=True, exclude={"options"})
        if not data and "options" not in body.model_fields_set:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        s = await _get_alive(survey_id)
        gone: list[int] = []
        if body.options is not None:
            keep = {norm_key(o.option1, o.option2) for o in body.options}
            before = await PriceSurveyPrice.filter(survey_id=s.id, option__deleted_at=None).select_related("option")
            gone = [r.option.id for r in before if norm_key(r.option.option1, r.option.option2) not in keep]
            used = await used_by_listings(s.product_id, set(gone))
            if used:
                raise HTTPException(
                    status_code=409,
                    detail=f"빠진 옵션을 마켓 등록이 쓰고 있습니다. 먼저 내리거나 이름만 고쳐 주세요: {', '.join(used)}",
                )
        async with in_transaction() as conn:
            if data:
                await s.update_from_dict(data).save(using_db=conn)
            if body.options is not None:
                pairs = await match_options(s.product_id, body.options, conn, rename=True)
                await record_prices(s.id, pairs, conn)
                if gone:
                    await PriceSurveyPrice.filter(survey_id=s.id, option_id__in=gone).using_db(conn).delete()
                    await soft_delete(gone, conn)
                await refresh_current_prices(s.product_id, conn)
        __import__("services.product.shipping_mode", fromlist=["kick"]).kick(s.product_id)   # 배송비 방식 다시 분류
        return await PriceSurveyService.get(s.id)

    @staticmethod
    async def add_option(survey_id: int, body) -> dict:
        """옵션 1개 추가. 이 조사에 같은 (맛, 용량) 조합이 이미 있으면 409. 제품에 같은 옵션이 있으면 그 id 를 쓴다."""
        s = await _get_alive(survey_id)
        key = norm_key(body.option1, body.option2)
        for r in await PriceSurveyPrice.filter(survey_id=s.id, option__deleted_at=None).select_related("option"):
            if norm_key(r.option.option1, r.option.option2) == key:
                raise HTTPException(status_code=409, detail=f"같은 옵션이 이미 있습니다: {body.option1} / {body.option2 or '-'}")
        async with in_transaction() as conn:
            pairs = await match_options(s.product_id, [body], conn)
            await record_prices(s.id, pairs, conn)
            await refresh_current_prices(s.product_id, conn)
        return await PriceSurveyService.get(s.id)

    @staticmethod
    async def patch_option(survey_id: int, option_id: int, body: PriceSurveyOptionPatch) -> dict:
        """옵션 1개를 제자리에서 수정 — id·price_cny 는 그대로라 저장된 판매가와 마켓 등록 연결이 유지된다."""
        data = body.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(status_code=400, detail="바꿀 내용이 없습니다.")
        s = await _get_alive(survey_id)
        opt = await ProductOption.get_or_none(id=option_id, product_id=s.product_id, deleted_at=None)
        if not opt or not await PriceSurveyPrice.filter(survey_id=s.id, option_id=opt.id).exists():
            raise HTTPException(status_code=404, detail="옵션을 찾을 수 없습니다.")
        new_key = (data.get("option1", opt.option1), data.get("option2", opt.option2))
        dup = any(
            norm_key(o.option1, o.option2) == norm_key(*new_key)
            for o in await ProductOption.filter(product_id=s.product_id, deleted_at=None).exclude(id=opt.id)
        )
        if dup:
            raise HTTPException(status_code=409, detail=f"같은 옵션이 이미 있습니다: {new_key[0]} / {new_key[1] or '-'}")
        data = _spec_patch(opt, data)
        await opt.update_from_dict(data).save(update_fields=[*data.keys(), "updated_at"])
        return await PriceSurveyService.get(s.id)

    @staticmethod
    async def delete_option(survey_id: int, option_id: int) -> dict:
        """옵션 1개만 지운다 (중복 옵션 정리용) — 소프트 삭제라 id 는 남는다. 그 옵션의 판매가(OptionPrice)는 함께 지워지고,
        대표 옵션 지정(base_option)은 비워진다. 다른 옵션은 손대지 않는다.
        살아 있는 마켓 등록(items[].option_id)이 이 옵션을 쓰면 409 — 주문 매칭이 깨지지 않게 먼저 내린다."""
        s = await _get_alive(survey_id)
        opt = await ProductOption.get_or_none(id=option_id, product_id=s.product_id, deleted_at=None)
        if not opt or not await PriceSurveyPrice.filter(survey_id=s.id, option_id=opt.id).exists():
            raise HTTPException(status_code=404, detail="옵션을 찾을 수 없습니다.")
        if await PriceSurveyPrice.filter(survey_id=s.id, option__deleted_at=None).count() <= 1:
            raise HTTPException(status_code=409, detail="마지막 옵션은 지울 수 없습니다.")
        used = await used_by_listings(s.product_id, {opt.id})
        if used:
            raise HTTPException(
                status_code=409,
                detail=f"마켓 등록에 쓰이는 옵션입니다. 먼저 내려 주세요: {', '.join(used)}",
            )
        async with in_transaction() as conn:
            await PriceSurveyPrice.filter(survey_id=s.id, option_id=opt.id).using_db(conn).delete()
            await soft_delete([opt.id], conn)
        return await PriceSurveyService.get(s.id)

    @staticmethod
    async def delete(survey_id: int) -> None:
        """조사 소프트 삭제 — 옵션(id)은 그대로 두고, 현재 원가만 남은 조사 기준으로 다시 맞춘다."""
        s = await _get_alive(survey_id)
        s.deleted_at = datetime.now(timezone.utc)
        async with in_transaction() as conn:
            await s.save(update_fields=["deleted_at", "updated_at"], using_db=conn)
            await refresh_current_prices(s.product_id, conn)
