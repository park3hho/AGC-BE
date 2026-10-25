from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from core.pricing_config import (
    DEFAULT_FEE_RATES,
    DEFAULT_FX_MARKUP_PCT,
    DEFAULT_SHIPPING_FEE,
    Platform,
)
from models.product.price_survey import PriceSurvey, PriceSurveyOption
from models.product.pricing import OptionPrice, ProductBundle, ProductPricing
from models.product.product import Product
from schemas.pricing import PricingSave
from services.pricing.exchange_rate_service import ExchangeRateService
from services.pricing.shipping_service import bundle_option_dict, bundle_suggestions, option_dict
from services.product.price_survey_service import alive_surveys
from services.product.product_service import alive_products
from services.product.serializers import product_dict


def _dec(v, places: int) -> Optional[str]:
    """소수 값은 DB 자릿수 그대로 문자열로 ("200.0000", "10.80")."""
    if v is None:
        return None
    return format(Decimal(str(v)), f".{places}f")


def parse_platform(platform: str) -> Platform:
    try:
        return Platform(platform)
    except ValueError:
        raise HTTPException(status_code=404, detail="알 수 없는 판매처입니다.")


async def _get_product(product_id: int) -> Product:
    p = await alive_products().get_or_none(id=product_id)
    if not p:
        raise HTTPException(status_code=404, detail="제품을 찾을 수 없습니다.")
    return p


async def _base_survey(product_id: int) -> Optional[PriceSurvey]:
    """기준 조사 = 살아 있는 조사 중 조사일 최근 → id 큰 순 1건."""
    return await alive_surveys().filter(product_id=product_id).order_by("-survey_date", "-id").first()


def _option_price_dict(option_id: int, op: Optional[OptionPrice], bundle_qty: int = 1) -> dict:
    """판매 옵션 1개의 판매가 + (네이버) 상품 나누기 직접 지정값. 저장 안 됐거나 옛 조사 기준이면 빈 값."""
    return {
        "option_id": option_id,
        "bundle_qty": bundle_qty,
        "sale_price": op.sale_price if op else None,
        "listing_group": op.listing_group if op else None,
        "is_base": op.is_base if op else False,
    }


def _pricing_dict(platform: Platform, pr: Optional[ProductPricing], base_survey_id: Optional[int],
                  option_ids: list[int], prices: dict[tuple[int, int], OptionPrice], current_fx: str) -> dict:
    """option_prices 는 기준 조사 options 순서·개수와 같다 (묶음 1).
    bundle_prices 는 묶음 2 이상으로 저장된 판매가 (응답 bundles 의 일부).
    저장된 survey_id 가 기준 조사와 다르면 판매가는 옛 옵션 기준이라 전부 null.
    fx_rate 는 저장 시점 환율(기록용). 저장 전이면 현재 환율 — 계산은 항상 응답의 fx(현재 환율)로 한다."""
    if pr is None:
        fees = DEFAULT_FEE_RATES[platform]
        return {
            "platform": platform.value, "saved": False, "survey_id": base_survey_id,
            "fx_rate": current_fx, "fx_date": None, "fx_markup_pct": _dec(DEFAULT_FX_MARKUP_PCT, 2),
            "shipping_fee": DEFAULT_SHIPPING_FEE, "platform_fee_rate": _dec(fees["platform_fee_rate"], 2),
            "payment_fee_rate": _dec(fees["payment_fee_rate"], 2),
            "option_prices": [_option_price_dict(oid, None) for oid in option_ids],
            "bundle_prices": [],
            "base_option_id": None,
            "updated_at": None,
        }
    same_survey = pr.survey_id == base_survey_id
    return {
        "platform": platform.value, "saved": True, "survey_id": pr.survey_id,
        "fx_rate": _dec(pr.fx_rate, 4), "fx_date": pr.fx_date.isoformat() if pr.fx_date else None,
        "fx_markup_pct": _dec(pr.fx_markup_pct, 2),
        "shipping_fee": pr.shipping_fee,
        "platform_fee_rate": _dec(pr.platform_fee_rate, 2), "payment_fee_rate": _dec(pr.payment_fee_rate, 2),
        "option_prices": [
            _option_price_dict(oid, prices.get((oid, 1)) if same_survey else None) for oid in option_ids
        ],
        "bundle_prices": [
            _option_price_dict(oid, op, n) for (oid, n), op in sorted(prices.items())
            if same_survey and n > 1 and oid in option_ids
        ],
        # 대표 옵션 — 옛 조사 기준이면 판매가처럼 null
        "base_option_id": pr.base_option_id if same_survey else None,
        "updated_at": pr.updated_at.isoformat(),
    }


async def _pricings(product_id: int, base_survey_id: Optional[int], option_ids: list[int],
                    platforms: list[Platform], current_fx: str) -> dict[str, dict]:
    rows = await ProductPricing.filter(product_id=product_id, platform__in=platforms)
    by_platform = {Platform(r.platform): r for r in rows}
    prices_by_pricing: dict[int, dict[tuple[int, int], OptionPrice]] = {r.id: {} for r in rows}
    if rows:
        for op in await OptionPrice.filter(pricing_id__in=list(prices_by_pricing)):
            prices_by_pricing[op.pricing_id][(op.option_id, op.bundle_qty)] = op
    result = {}
    for pf in platforms:
        pr = by_platform.get(pf)
        prices = prices_by_pricing[pr.id] if pr else {}
        result[pf.value] = _pricing_dict(pf, pr, base_survey_id, option_ids, prices, current_fx)
    return result


async def _bundles(survey_id: Optional[int], options: list[PriceSurveyOption], product_code: str) -> list[dict]:
    """묶음 판매 옵션 = 10kg 제안 + 어느 판매처에든 판매가가 저장된 묶음. 조사 옵션 순서 → 묶음 수 순서.
    suggested = 규칙이 제안한 묶음 (저장된 것과 겹치면 둘 다 참일 수 있음, saved 는 판매가가 있는지)."""
    if not survey_id or not options:
        return []
    by_id = {o.id: o for o in options}
    saved = set(
        await OptionPrice.filter(pricing__survey_id=survey_id, option_id__in=list(by_id), bundle_qty__gt=1)
        .values_list("option_id", "bundle_qty")
    )
    adopted = set(
        await ProductBundle.filter(option_id__in=list(by_id), deleted_at=None).values_list("option_id", "bundle_qty")
    )
    suggested = {(o.id, n) for o, n in bundle_suggestions(options)}
    order = {o.id: i for i, o in enumerate(options)}
    keys = sorted(saved | suggested | adopted, key=lambda k: (order[k[0]], k[1]))
    return [
        {**bundle_option_dict(by_id[oid], n, suggested=(oid, n) in suggested), "saved": (oid, n) in saved,
         "adopted": (oid, n) in adopted,   # 판매 옵션으로 채택함 (판매가는 비어 있을 수 있음)
         # 마켓 판매자 코드 (쿠팡 externalVendorSku) — 주문이 들어오면 이 코드로 조사 옵션 × 묶음을 찾는다
         "sku": f"{product_code}-{oid}x{n}"}
        for oid, n in keys
    ]


class PricingService:
    @staticmethod
    async def get(product_id: int) -> dict:
        p = await _get_product(product_id)
        survey = await _base_survey(p.id)
        options = await PriceSurveyOption.filter(survey_id=survey.id).order_by("id") if survey else []
        option_ids = [o.id for o in options]
        fx = await ExchangeRateService.current()
        return {
            "product": product_dict(p),
            "survey": (
                {"id": survey.id, "code": survey.code, "survey_date": survey.survey_date.isoformat()}
                if survey else None
            ),
            "fx": fx,                                         # 현재 환율 — 원가·배송비 계산에 쓴다
            "options": [option_dict(o) for o in options],     # 옵션 + 배송비(위안)
            "bundles": await _bundles(survey.id if survey else None, options, p.code),   # 묶음 판매 옵션 (제안 + 저장된 것)
            "pricings": await _pricings(
                p.id, survey.id if survey else None, option_ids, list(Platform), fx["cny_krw"]
            ),
        }

    @staticmethod
    async def save(product_id: int, platform: Platform, body: PricingSave) -> dict:
        p = await _get_product(product_id)
        survey = await alive_surveys().get_or_none(id=body.survey_id, product_id=p.id)
        if not survey:
            raise HTTPException(status_code=400, detail="이 제품의 가격 조사가 아닙니다.")
        seen = set()
        for op in body.option_prices:
            if (op.option_id, op.bundle_qty) in seen:
                raise HTTPException(
                    status_code=400,
                    detail=f"같은 옵션의 판매가가 두 번 들어 있습니다: option_id {op.option_id} 묶음 {op.bundle_qty}",
                )
            seen.add((op.option_id, op.bundle_qty))
        survey_option_ids = set(await PriceSurveyOption.filter(survey_id=survey.id).values_list("id", flat=True))
        wrong = [op.option_id for op in body.option_prices if op.option_id not in survey_option_ids]
        if wrong:
            raise HTTPException(status_code=400, detail=f"이 가격 조사의 옵션이 아닙니다: option_id {wrong[0]}")
        if body.base_option_id is not None and (body.base_option_id, 1) not in seen:
            raise HTTPException(status_code=400, detail="대표 옵션은 판매가가 있는 이 조사의 옵션이어야 합니다.")

        fields = {
            "survey_id": survey.id,
            "fx_rate": body.fx_rate,
            "fx_date": None,                    # 환율 API 연동 전까지 비움
            "fx_markup_pct": body.fx_markup_pct,
            "platform_fee_rate": body.platform_fee_rate,
            "payment_fee_rate": body.payment_fee_rate,
            "base_option_id": body.base_option_id,
        }
        if body.shipping_fee is not None:      # 더 이상 계산에 안 씀 — 보내면 기록만
            fields["shipping_fee"] = body.shipping_fee
        # 판매처 설정 + 옵션 판매가 전체 교체는 전부 저장되거나 전부 안 되거나
        try:
            async with in_transaction() as conn:
                pr = await (
                    ProductPricing.filter(product_id=p.id, platform=platform).using_db(conn).select_for_update().first()
                )
                if pr:
                    await pr.update_from_dict(fields).save(using_db=conn)
                else:
                    pr = await ProductPricing.create(product_id=p.id, platform=platform, using_db=conn, **fields)
                await OptionPrice.filter(pricing_id=pr.id).using_db(conn).delete()
                if body.option_prices:
                    await OptionPrice.bulk_create(
                        [OptionPrice(pricing_id=pr.id, option_id=op.option_id, bundle_qty=op.bundle_qty,
                                     sale_price=op.sale_price,
                                     listing_group=op.listing_group, is_base=op.is_base)
                         for op in body.option_prices],
                        using_db=conn,
                    )
        except IntegrityError:
            # 같은 판매처 첫 저장이 동시에 두 번 들어와 product+platform unique 에 걸림 → 롤백됨
            raise HTTPException(status_code=409, detail="동시에 저장이 겹쳤습니다. 다시 시도해주세요.")

        base = await _base_survey(p.id)
        option_ids = (
            list(await PriceSurveyOption.filter(survey_id=base.id).order_by("id").values_list("id", flat=True))
            if base else []
        )
        current_fx = (await ExchangeRateService.current())["cny_krw"]
        pricings = await _pricings(p.id, base.id if base else None, option_ids, [platform], current_fx)
        return pricings[platform.value]


async def _survey_option(product_id: int, option_id: int) -> PriceSurveyOption:
    """기준 조사(최신)의 옵션만 묶음으로 쓸 수 있다."""
    survey = await _base_survey(product_id)
    opt = await PriceSurveyOption.get_or_none(id=option_id, survey_id=survey.id) if survey else None
    if not opt:
        raise HTTPException(status_code=400, detail="이 제품 최신 가격 조사의 옵션이 아닙니다.")
    return opt


class BundleService:
    """묶음 판매 옵션 채택 · 빼기. 판매가는 가격 책정 저장(PUT pricing)으로 따로 넣는다."""

    @staticmethod
    async def adopt(product_id: int, option_id: int, bundle_qty: int, user_id: Optional[int],
                    source: str = "manual") -> dict:
        p = await _get_product(product_id)
        opt = await _survey_option(p.id, option_id)
        d = bundle_option_dict(opt, bundle_qty)
        if d["over_limit"]:
            raise HTTPException(status_code=400, detail="30kg 를 넘어 집운 소형으로 보낼 수 없습니다.")
        row = await ProductBundle.get_or_none(option_id=opt.id, bundle_qty=bundle_qty)
        if row:
            if row.deleted_at is not None:
                row.deleted_at, row.created_by_id, row.source = None, user_id, source
                await row.save()
        else:
            row = await ProductBundle.create(product_id=p.id, option_id=opt.id, bundle_qty=bundle_qty,
                                             source=source, created_by_id=user_id)
        return {"key": d["key"], "adopted": True}

    @staticmethod
    async def drop(product_id: int, option_id: int, bundle_qty: int) -> dict:
        """채택만 푼다. 저장된 판매가는 가격 책정에서 지우고 저장해야 없어진다."""
        await _get_product(product_id)
        row = await ProductBundle.get_or_none(product_id=product_id, option_id=option_id, bundle_qty=bundle_qty,
                                              deleted_at=None)
        if row:
            row.deleted_at = datetime.now(timezone.utc)
            await row.save(update_fields=["deleted_at", "updated_at"])
        return {"key": f"{option_id}x{bundle_qty}", "adopted": False}