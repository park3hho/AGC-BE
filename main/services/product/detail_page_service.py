"""상세페이지(디자인) — 템플릿 채우기 · 저장 · 검수(휴먼 체크) · 공통 안내. BE DESIGN.md §6.4"""

import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError
from tortoise.transactions import in_transaction

from core.company_info_config import LINK_FOOD_AGENCY_REG_NO
from core.detail_page_config import (
    DEFAULT_COMMON,
    MARKER_RE,
    REG_NO_PLACEHOLDER_RE,
    REVIEW_HISTORY_SIZE,
    DetailStatus,
    ExportPlatform,
    ReviewAction,
)
from core.pricing_config import MARKET_PLATFORMS, Platform
from models.product.detail_page import DetailPage, DetailPageCommon, DetailPageReview
from models.product.price_survey import PriceSurveyOption
from models.product.pricing import ProductPricing
from models.product.product import Product
from schemas.detail_page import DetailCommonSave, DetailContent, DetailPageApprove, DetailPageSave
from services.company_account.company_info_service import linked_value
from services.product import detail_export_service as exports
from services.product.price_survey_service import alive_surveys
from services.product.product_service import alive_products
from services.product.serializers import product_dict

COMMON_ID = 1
STATUS_NONE = "none"        # 목록 필터 — 상세페이지가 아직 없는 제품


# ── 확인 표시 · 등록번호 ─────────────────────────────────────────

def count_markers(value) -> int:
    """[[...]] 확인 표시 개수 — 문자열·목록·dict 안을 전부 센다."""
    if isinstance(value, str):
        return len(MARKER_RE.findall(value))
    if isinstance(value, dict):
        return sum(count_markers(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(count_markers(v) for v in value)
    return 0


# 사람이 읽는 칸 이름 — 남은 확인 표시 목록에 쓴다
_SECTION_LABEL = {"hero": "S1 첫 화면", "points": "S2 포인트", "flavors": "S3 구성", "info": "S4 제품 정보",
                  "howto": "S5 이렇게 즐겨요", "notice": "S6 안내", "notice_title": "S6 제목", "seller": "S6 판매자"}


def _spots(value, path: str) -> list[dict]:
    out: list[dict] = []
    if isinstance(value, str):
        out += [{"path": path, "text": m.group(0)} for m in MARKER_RE.finditer(value)]
    elif isinstance(value, dict):
        for k, v in value.items():
            out += _spots(v, f"{path}.{k}" if path else k)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            # 제품 정보 줄은 라벨로 부른다 (rows[원재료])
            label = v.get("label") if isinstance(v, dict) and isinstance(v.get("label"), str) else None
            out += _spots(v, f"{path}[{label or i + 1}]")
    return out


def marker_spots(value) -> list[dict]:
    """[[...]] 확인 표시가 남은 자리 — [{path, where, text}]. where 는 사람이 읽는 위치 ("S4 제품 정보 rows[원재료]")."""
    return [{**s, "where": _where(s["path"])} for s in _spots(value, "")]


def _where(path: str) -> str:
    """"info.rows[원재료].value" → "S4 제품 정보 · 원재료"."""
    tokens = re.findall(r"([^.\[\]]+)|\[([^\]]+)\]", path)
    head = tokens[0][0] if tokens else path
    parts: list[str] = []
    for key, idx in tokens[1:]:
        if key and key != "value":
            parts.append(key)
        elif idx:
            if idx.isdigit() and parts:
                parts[-1] = f"{parts[-1]} {idx}"      # badges[2] → "badges 2"
            elif not idx.isdigit():
                parts = [p for p in parts if p != "rows"] + [idx]   # rows[원재료] → "원재료"
    return " · ".join([_SECTION_LABEL.get(head, head), *parts])


def _markers_block(content: dict, common_payload: dict, action: str) -> None:
    """확인 표시가 남아 있으면 409 — 고객용 이미지에 노란 표시가 그대로 찍히는 걸 막는다 (2026-10-26 사용자 요청)."""
    spots = marker_spots(content) + marker_spots({k: v for k, v in common_payload.items() if k != "reg_no"})
    if spots:
        listed = ", ".join(f"{s['where']} {s['text']}" for s in spots[:8])
        more = f" 외 {len(spots) - 8}칸" if len(spots) > 8 else ""
        raise HTTPException(
            status_code=409,
            detail=f"확인 표시 [[...]]가 {len(spots)}칸 남아 있어 {action} 수 없습니다: {listed}{more}",
        )


def reg_no_ready(reg_no: str) -> bool:
    return bool(reg_no) and not REG_NO_PLACEHOLDER_RE.match(reg_no) and not MARKER_RE.search(reg_no)


# ── 공통 안내 ───────────────────────────────────────────────

def _common_payload(c: DetailPageCommon) -> dict:
    return {"reg_no": c.reg_no, "seller": c.seller, "notice_title": c.notice_title, "notice": c.notice}


def _common_dict(c: DetailPageCommon, reg_no_linked: bool = False) -> dict:
    payload = _common_payload(c)
    return {
        **payload,
        "reg_no_ready": reg_no_ready(c.reg_no),
        "reg_no_linked": reg_no_linked,     # true = 회사 정보 › 기본 정보에서 가져온 값 (S6 에서는 못 고침)
        "marker_count": count_markers({k: v for k, v in payload.items() if k != "reg_no"}),
        "updated_at": c.updated_at.isoformat(),
    }


async def _apply_common(data: dict, user_id: int, reason: str) -> int:
    """공통 안내를 data 로 바꾼다. 실제로 바뀌었으면 승인된 상세페이지를 모두 검수 대기로 되돌리고 그 수를 준다."""
    await _get_common()
    async with in_transaction() as conn:
        c = await DetailPageCommon.filter(id=COMMON_ID).using_db(conn).select_for_update().first()
        if _common_payload(c) == data:
            return 0
        await c.update_from_dict({**data, "updated_by_id": user_id}).save(using_db=conn)
        approved = await DetailPage.filter(status=DetailStatus.APPROVED).using_db(conn)
        for dp in approved:
            dp.status = DetailStatus.REVIEW
            await dp.save(using_db=conn, update_fields=["status", "updated_at"])
            await _log(dp.id, ReviewAction.RESET, user_id, reason, conn=conn)
        return len(approved)


async def _get_common() -> DetailPageCommon:
    c = await DetailPageCommon.get_or_none(id=COMMON_ID)
    if c:
        return c
    try:
        return await DetailPageCommon.create(id=COMMON_ID, **DEFAULT_COMMON)
    except IntegrityError:          # 처음 두 요청이 동시에 만들려 함
        return await DetailPageCommon.get(id=COMMON_ID)


# ── 템플릿 채우기 ───────────────────────────────────────────

def _uniq(values) -> list:
    out = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out


async def _latest_options(product_id: int) -> list[PriceSurveyOption]:
    survey = await alive_surveys().filter(product_id=product_id).order_by("-survey_date", "-id").first()
    return list(await PriceSurveyOption.filter(survey_id=survey.id).order_by("id")) if survey else []


def _photos(p: Product, options: list[PriceSurveyOption]) -> list[dict]:
    """고를 수 있는 사진 — 대표 사진 + 추가 사진(갤러리) + 최근 조사 옵션별 사진 (같은 파일은 한 번)."""
    photos, seen = [], set()
    for url, label in [(p.photo_url, "대표")] + [
        (u, f"추가 {i}") for i, u in enumerate(p.photos or [], 1)
    ] + [
        (o.photo_url, " · ".join(x for x in (o.option1, o.option2) if x)) for o in options
    ]:
        if url and url not in seen:
            seen.add(url)
            photos.append({"url": url, "label": label})
    return photos


def build_template(p: Product, options: list[PriceSurveyOption]) -> dict:
    """제품 + 최근 조사 옵션으로 템플릿을 채운다. 사람이 써야 하는 칸은 [[...]] 확인 표시로 남긴다
    (남아 있어도 확인은 되지만 FE 가 경고를 보여준다)."""
    sizes = _uniq(o.option2 for o in options)
    size_text = ", ".join(sizes) if sizes else "[[용량 · 수량]]"
    flavor_names = _uniq(o.option1 for o in options)
    first_photo = {}
    for o in options:
        if o.photo_url:
            first_photo.setdefault(o.option1, o.photo_url)
    hero_photo = p.photo_url or next((first_photo[n] for n in flavor_names if n in first_photo), None)
    # 포인트 사진은 자동으로 채우지 않는다 — 맞는 사진만 사람·에이전트가 고른다 (2026-10-25, 사진 잘림 방지)
    name = p.title_ko or p.title_cn

    content = {
        "hero": {
            "eyebrow": "[[한 줄 소개]]",
            "headline": "[[헤드라인 첫 줄]]\n*[[강조]]* [[둘째 줄]]",
            "name": name,
            "name_sub": f"{p.title_cn} · {sizes[0]}" if sizes else p.title_cn,
            "badges": [{"value": "[[숫자]]", "label": "[[설명]]"} for _ in range(3)],
            "photo_url": hero_photo,
        },
        "points": {
            "title": "이런 음료예요",
            "lead": "[[어떤 분께 맞는지 한 줄]]",
            "items": [
                {"title": "[[포인트]]", "desc": "[[설명]]", "big": "", "big_unit": "", "photo_url": None}
                for i in range(3)
            ],
        },
        "flavors": {
            "title": "맛을 골라주세요" if len(flavor_names) > 1 else "이렇게 구성돼요",
            "lead": (
                f"{len(flavor_names)}가지 맛 모두 {sizes[0]} 구성이에요." if len(flavor_names) > 1 and len(sizes) == 1
                else f"용량 · 수량: {size_text}"
            ),
            "items": [
                {"name": n, "name_cn": "", "desc": "[[맛 설명]]", "chips": [], "photo_url": first_photo.get(n)}
                for n in flavor_names
            ],
            "notes": ["사진 속 과일은 맛을 표현한 연출 이미지예요."],
        },
        "info": {
            "title": "제품 정보",
            "rows": [
                {"label": "제품명", "value": f"{name} ({p.title_cn})" if p.title_ko else p.title_cn},
                # 제품에 저장된 정보(리서치 때 찾은 값)가 있으면 그대로 쓰고, 없을 때만 [[...]] 확인 표시를 남긴다
                {"label": "브랜드 · 제조사", "value": p.manufacturer or "[[제조사]]"},
                {"label": "원산지", "value": "중국"},
                {"label": "용량 · 수량", "value": size_text},
                {"label": "원재료", "value": p.ingredients or "[[실제 라벨 기준 원재료]]"},
                *([{"label": "알레르기", "value": f"{p.allergens} 함유"}] if p.allergens else []),
                {"label": "소비기한", "value": f"제조일로부터 {p.shelf_life}" if p.shelf_life else "제품 라벨 별도 표기일까지"},
                {"label": "보관 방법", "value": p.storage or "직사광선을 피해 서늘한 곳에 보관, 개봉 후 냉장 보관"},
            ],
            "nutrition": [],
            "note": "",
        },
        "howto": {
            "title": "이렇게 드세요",
            "items": [
                {"icon": "cold", "title": "차갑게", "desc": "냉장고에 두었다가 시원하게 마시면 더 맛있어요"},
                {"icon": "cup", "title": "[[추천 상황]]", "desc": "[[설명]]"},
                {"icon": "bottle", "title": "개봉 후엔 냉장", "desc": "뚜껑을 연 뒤에는 냉장 보관하고 빨리 드세요"},
            ],
        },
    }
    return DetailContent.model_validate(content).model_dump()


# ── 응답 모양 ───────────────────────────────────────────────

def _user_ref(u) -> Optional[dict]:
    return {"id": u.id, "name": u.name} if u else None


def _page_summary(dp: DetailPage) -> dict:
    return {
        "status": dp.status.value if hasattr(dp.status, "value") else dp.status,
        "created_at": dp.created_at.isoformat(),          # 디자인 시작 (첫 저장)
        "updated_at": dp.updated_at.isoformat(),
        "updated_by": _user_ref(dp.updated_by),
        "reviewed_at": dp.reviewed_at.isoformat() if dp.reviewed_at else None,
        "reviewed_by": _user_ref(dp.reviewed_by),
        "review_note": dp.review_note,
    }


async def _page_dict(dp: DetailPage) -> dict:
    await dp.fetch_related("updated_by", "reviewed_by")
    c_hash = exports.content_hash(dp.content, _common_payload(await _get_common()))
    reviews = await (
        DetailPageReview.filter(page_id=dp.id).order_by("-id").limit(REVIEW_HISTORY_SIZE).prefetch_related("user")
    )
    return {
        **_page_summary(dp),
        "id": dp.id,
        "content": dp.content,
        "review_checks": dp.review_checks or [],
        "marker_count": count_markers(dp.content),
        "markers": marker_spots(dp.content),   # 남은 확인 표시 자리 [{path, where, text}]
        "content_hash": c_hash,                              # 내보내기 때 그린 시점 확인용 (content + 공통 안내)
        "exports": await exports.latest_exports(dp.id, c_hash),
        "reviews": [
            {
                "action": r.action.value if hasattr(r.action, "value") else r.action,
                "user": _user_ref(r.user), "note": r.note, "checks": r.checks or [],
                "created_at": r.created_at.isoformat(),
            }
            for r in reviews
        ],
    }


# ── 가격 책정 완료 제품 ──────────────────────────────────────

async def _priced_product_ids() -> list[int]:
    """모든 판매처 판매가를 저장한 제품 (FE utils/pricing.pricingStatusOf 의 'done' 과 같은 기준)."""
    need = {pf.value for pf in MARKET_PLATFORMS}     # 자사몰가는 없어도 완료
    have: dict[int, set] = {}
    for r in await ProductPricing.filter(product__deleted_at=None).values("product_id", "platform"):
        pf = r["platform"]
        have.setdefault(r["product_id"], set()).add(getattr(pf, "value", pf))
    return [pid for pid, pfs in have.items() if need <= pfs]


async def _get_product(product_id: int) -> Product:
    p = await alive_products().get_or_none(id=product_id)
    if not p:
        raise HTTPException(status_code=404, detail="제품을 찾을 수 없습니다.")
    return p


async def _get_page(product_id: int) -> DetailPage:
    await _get_product(product_id)
    dp = await DetailPage.get_or_none(product_id=product_id)
    if not dp:
        raise HTTPException(status_code=404, detail="아직 상세페이지가 없습니다.")
    return dp


async def _log(dp_id: int, action: ReviewAction, user_id: Optional[int], note=None, checks=None, conn=None):
    await DetailPageReview.create(page_id=dp_id, action=action, user_id=user_id, note=note, checks=checks,
                                  using_db=conn)


class DetailPageService:
    @staticmethod
    async def list(status: Optional[str], q: Optional[str]) -> dict:
        """가격 책정이 끝난 제품 + 상세페이지 상태. counts 는 필터와 상관없이 전체 기준."""
        ids = await _priced_product_ids()
        products = await alive_products().filter(id__in=ids).order_by("-created_at", "-id")
        pages = {
            dp.product_id: dp
            for dp in await DetailPage.filter(product_id__in=ids).prefetch_related("updated_by", "reviewed_by")
        }
        counts = {STATUS_NONE: 0, **{s.value: 0 for s in DetailStatus}}
        items = []
        word = (q or "").strip().lower()
        for p in products:
            dp = pages.get(p.id)
            st = (dp.status.value if hasattr(dp.status, "value") else dp.status) if dp else STATUS_NONE
            counts[st] += 1
            if status and status != st:
                continue
            if word and not any(word in (v or "").lower() for v in (p.code, p.title_ko, p.title_cn)):
                continue
            items.append({"product": product_dict(p), "page": _page_summary(dp) if dp else None})
        return {"items": items, "total": len(items), "counts": counts}

    @staticmethod
    async def get(product_id: int) -> dict:
        p = await _get_product(product_id)
        options = await _latest_options(p.id)
        dp = await DetailPage.get_or_none(product_id=p.id)
        common = await _get_common()
        template = build_template(p, options)
        return {
            "product": product_dict(p),
            "page": await _page_dict(dp) if dp else None,
            "template": template,          # 페이지가 없을 때 처음 채울 값 (저장하지 않은 상태)
            "photos": _photos(p, options),
            "common": _common_dict(common, reg_no_linked=await linked_value(LINK_FOOD_AGENCY_REG_NO) is not None),
        }

    @staticmethod
    async def save(product_id: int, body: DetailPageSave, user_id: int) -> dict:
        """내용 저장 — 없으면 초안으로 만든다. 승인된 페이지 내용이 바뀌면 검수 대기로 되돌린다."""
        p = await _get_product(product_id)
        content = body.content.model_dump()
        async with in_transaction() as conn:
            dp = await DetailPage.filter(product_id=p.id).using_db(conn).select_for_update().first()
            if dp is None:
                try:
                    dp = await DetailPage.create(product_id=p.id, content=content, updated_by_id=user_id,
                                                 status=DetailStatus.DRAFT, using_db=conn)
                except IntegrityError:
                    raise HTTPException(status_code=409, detail="동시에 저장이 겹쳤습니다. 다시 시도해주세요.")
            else:
                changed = dp.content != content
                if changed:
                    dp.content = content
                    dp.updated_by_id = user_id
                    if dp.status == DetailStatus.APPROVED:
                        dp.status = DetailStatus.REVIEW
                        await _log(dp.id, ReviewAction.RESET, user_id, "승인 뒤 내용이 바뀌어 다시 검수해요", conn=conn)
                    await dp.save(using_db=conn)
            if body.submit and dp.status in (DetailStatus.DRAFT, DetailStatus.CHANGES):
                dp.status = DetailStatus.REVIEW
                dp.updated_by_id = user_id
                await dp.save(using_db=conn)
                await _log(dp.id, ReviewAction.SUBMIT, user_id, conn=conn)
        return await _page_dict(await DetailPage.get(id=dp.id))

    @staticmethod
    async def approve(product_id: int, body: DetailPageApprove, user_id: int) -> dict:
        """휴먼 체크 = 사람이 미리보기를 보고 "확인" 한 번 (2026-10-22 사용자 결정 — 체크리스트 없음).
        초안 · 검수 대기 · 수정 필요 어디서든 바로 승인한다. 등록번호는 경고만 (FE).
        확인 표시([[...]])가 내용 · 공통 안내에 남아 있으면 409 (2026-10-26 사용자 요청 — 10-22 에 풀었던 조건을 다시 건다).
        이미 승인된 페이지 상태는 건드리지 않는다 (내보내기에서 막힌다)."""
        async with in_transaction() as conn:
            dp = await DetailPage.filter(product_id=product_id).using_db(conn).select_for_update().first()
            if dp is None:
                await _get_page(product_id)      # 404 메시지
            if dp.status == DetailStatus.APPROVED:
                raise HTTPException(status_code=400, detail="이미 확인(승인)된 상세페이지입니다.")
            _markers_block(dp.content, _common_payload(await _get_common()), "확인(승인)할")
            dp.status = DetailStatus.APPROVED
            dp.reviewed_by_id = user_id
            dp.reviewed_at = datetime.now(timezone.utc)
            dp.review_note = (body.note or "").strip() or None
            dp.review_checks = None
            await dp.save(using_db=conn)
            await _log(dp.id, ReviewAction.APPROVE, user_id, dp.review_note, conn=conn)
        return await _page_dict(await DetailPage.get(id=dp.id))

    @staticmethod
    async def request_changes(product_id: int, note: str, user_id: int) -> dict:
        async with in_transaction() as conn:
            dp = await DetailPage.filter(product_id=product_id).using_db(conn).select_for_update().first()
            if dp is None:
                await _get_page(product_id)
            if dp.status not in (DetailStatus.REVIEW, DetailStatus.APPROVED):
                raise HTTPException(status_code=400, detail="검수 대기 · 승인 상태에서만 수정을 요청할 수 있습니다.")
            dp.status = DetailStatus.CHANGES
            dp.reviewed_by_id = user_id
            dp.reviewed_at = datetime.now(timezone.utc)
            dp.review_note = note
            dp.review_checks = None
            await dp.save(using_db=conn)
            await _log(dp.id, ReviewAction.CHANGES, user_id, note, conn=conn)
        return await _page_dict(await DetailPage.get(id=dp.id))

    @staticmethod
    async def save_export(product_id: int, platform: ExportPlatform, c_hash: str, template: str,
                          blobs: "list[bytes]", user_id: int) -> dict:
        """상세 이미지 조각(네이버 PNG · 쿠팡 JPG) 저장 — 승인된 페이지 · 그린 시점 해시가 지금과 같을 때만."""
        p = await _get_product(product_id)
        dp = await _get_page(product_id)
        exports.require_approved(dp)
        common_payload = _common_payload(await _get_common())
        _markers_block(dp.content, common_payload, "이미지로 내보낼")
        now_hash = exports.content_hash(dp.content, common_payload)
        if c_hash != now_hash:
            raise HTTPException(status_code=409, detail="그린 뒤 상세페이지가 바뀌었습니다. 다시 불러와 내보내주세요.")
        meta = exports.check_slices(platform, blobs)
        e = await exports.store_export(dp, p.code, platform, blobs, meta, now_hash, template, user_id)
        await e.fetch_related("created_by")
        return exports.export_dict(e, now_hash)

    @staticmethod
    async def get_common() -> dict:
        linked = await linked_value(LINK_FOOD_AGENCY_REG_NO)
        return _common_dict(await _get_common(), reg_no_linked=linked is not None)

    @staticmethod
    async def save_common(body: DetailCommonSave, user_id: int) -> dict:
        """공통 안내 저장. 바뀌었으면 승인된 상세페이지를 모두 검수 대기로 되돌린다 (승인 = 지금 보이는 그대로 확인).
        등록번호가 회사 정보 › 기본 정보에 연결돼 있으면 보낸 reg_no 대신 그 값을 쓴다."""
        data = body.model_dump()
        linked = await linked_value(LINK_FOOD_AGENCY_REG_NO)
        if linked is not None:
            data["reg_no"] = linked
        reset = await _apply_common(data, user_id, "공통 안내가 바뀌어 다시 검수해요")
        return {
            "common": _common_dict(await DetailPageCommon.get(id=COMMON_ID), reg_no_linked=linked is not None),
            "reset_count": reset,
        }

    @staticmethod
    async def sync_linked_reg_no(user_id: int) -> int:
        """회사 정보 › 기본 정보의 영업등록번호가 바뀌면 부른다. S6 등록번호를 맞추고 되돌린 상세페이지 수를 준다."""
        linked = await linked_value(LINK_FOOD_AGENCY_REG_NO)
        if linked is None:
            return 0
        c = await _get_common()
        return await _apply_common(
            {**_common_payload(c), "reg_no": linked}, user_id, "등록번호(회사 정보)가 바뀌어 다시 검수해요"
        )
