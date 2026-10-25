"""마켓 등록 기록 (판매 › 상품 › 상품 상세의 '마켓 등록'). 제품 1 : N.

- 직접 추가 · 수정 · 삭제(소프트).
- 쿠팡에서 불러오기: 셀러 상품 목록 → 상품마다 상세(옵션) → externalVendorSku `{제품 코드}-{옵션 id}` 로 제품을 찾는다.
  같은 (판매처, 마켓 상품번호)가 있으면 덮어쓰고, 사람이 지운 것은 다시 살리지 않는다. 제품을 못 찾은 상품은 건너뛴다.
  키·응답 본문은 로그에 남기지 않는다."""

import re
import urllib.parse
from datetime import datetime, timezone

from fastapi import HTTPException
from tortoise.exceptions import IntegrityError

from core.pricing_config import Platform
from models.product.listing import MarketListing
from models.product.product import Product
from schemas.listing import ListingCreate, ListingUpdate
from services.order.market_clients import KST, MarketApiError, _coupang_get, coupang_vendor_id

# `{제품 코드}-{옵션 id}` · 묶음 판매면 끝에 `x{묶음 수}` (예: PR-261020-0007-66x2 = 옵션 66 두 개 묶음)
SKU_RE = re.compile(r"^(PR-\d{6}-[0-9A-Fa-f]{4})(?:-(\d+)(?:[xX](\d+))?)?$")
COUPANG_PRODUCTS_PATH = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
COUPANG_PAGE_SIZE = 100
COUPANG_MAX_PAGES = 20          # 2,000개 — 그보다 많아지면 그때 늘린다
COUPANG_VIEW_URL = "https://www.coupang.com/vp/products/{pid}"


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def alive():
    return MarketListing.filter(deleted_at=None, product__deleted_at=None)


def listing_dict(x: MarketListing) -> dict:
    return {
        "id": x.id,
        "product_id": x.product_id,
        "platform": x.platform.value if hasattr(x.platform, "value") else x.platform,
        "market_product_id": x.market_product_id,
        "title": x.title,
        "url": x.url,
        "status": x.status,
        "listed_at": _iso(x.listed_at),
        "items": x.items or [],
        "source": x.source,
        "synced_at": _iso(x.synced_at),
        "memo": x.memo,
        "created_at": x.created_at.isoformat(),
        "updated_at": x.updated_at.isoformat(),
    }


class ListingService:
    @staticmethod
    async def list(product_id: int | None) -> list[dict]:
        qs = alive()
        if product_id:
            qs = qs.filter(product_id=product_id)
        rows = await qs.order_by("product_id", "platform", "listed_at", "id")
        return [listing_dict(x) for x in rows]

    @staticmethod
    async def create(body: ListingCreate, auth: dict) -> dict:
        if not await Product.filter(id=body.product_id, deleted_at=None).exists():
            raise HTTPException(status_code=404, detail="제품을 찾을 수 없습니다.")
        old = await MarketListing.get_or_none(platform=body.platform, market_product_id=body.market_product_id)
        fields = dict(title=body.title, url=body.url, listed_at=body.listed_at, memo=body.memo)
        if old and old.deleted_at is None:
            raise HTTPException(status_code=409, detail="이미 등록된 마켓 상품번호입니다.")
        if old:     # 지웠던 것을 다시 추가 → 그 행을 살린다 (unique 라 새로 못 만든다)
            for k, v in fields.items():
                setattr(old, k, v)
            old.product_id, old.deleted_at, old.source = body.product_id, None, "manual"
            await old.save()
            return listing_dict(old)
        try:
            x = await MarketListing.create(
                product_id=body.product_id, platform=body.platform, market_product_id=body.market_product_id,
                source="manual", created_by_id=auth.get("user_id"), **fields,
            )
        except IntegrityError:
            raise HTTPException(status_code=409, detail="이미 등록된 마켓 상품번호입니다.") from None
        return listing_dict(x)

    @staticmethod
    async def update(listing_id: int, body: ListingUpdate) -> dict:
        x = await MarketListing.get_or_none(id=listing_id, deleted_at=None)
        if not x:
            raise HTTPException(status_code=404, detail="마켓 등록 기록을 찾을 수 없습니다.")
        for k in body.model_fields_set:
            setattr(x, k, getattr(body, k))
        await x.save()
        return listing_dict(x)

    @staticmethod
    async def delete(listing_id: int) -> None:
        x = await MarketListing.get_or_none(id=listing_id, deleted_at=None)
        if not x:
            raise HTTPException(status_code=404, detail="마켓 등록 기록을 찾을 수 없습니다.")
        x.deleted_at = datetime.now(timezone.utc)
        await x.save(update_fields=["deleted_at", "updated_at"])

    # ── 쿠팡에서 불러오기 ─────────────────────────────────────

    @staticmethod
    async def sync_coupang(dry_run: bool = False) -> dict:
        try:
            found = await _coupang_listings()
        except (MarketApiError, KeyError) as e:
            raise HTTPException(status_code=502, detail=f"쿠팡 상품을 불러오지 못했습니다 ({str(e)[:120]}).") from None

        codes = {f["product_code"] for f in found if f["product_code"]}
        products = {p.code: p.id for p in await Product.filter(code__in=list(codes), deleted_at=None)}
        now = datetime.now(timezone.utc)
        result = {"total": len(found), "created": 0, "updated": 0, "skipped_deleted": 0, "unmatched": [], "items": []}
        for f in found:
            pid = products.get(f["product_code"] or "")
            if not pid:
                result["unmatched"].append({"market_product_id": f["market_product_id"], "title": f["title"]})
                continue
            values = dict(product_id=pid, title=f["title"], url=f["url"], status=f["status"],
                          listed_at=f["listed_at"], items=f["items"], source="api", synced_at=now)
            result["items"].append({**{k: _iso(v) for k, v in values.items()}, "market_product_id": f["market_product_id"]})
            if dry_run:
                continue
            old = await MarketListing.get_or_none(platform=Platform.COUPANG, market_product_id=f["market_product_id"])
            if old and old.deleted_at is not None:
                result["skipped_deleted"] += 1
                continue
            if old:
                for k, v in values.items():
                    setattr(old, k, v)
                await old.save()
                result["updated"] += 1
            else:
                await MarketListing.create(platform=Platform.COUPANG, market_product_id=f["market_product_id"], **values)
                result["created"] += 1
        return result


def _parse_kst(v) -> datetime | None:
    """쿠팡 시각 '2026-10-24T18:05:42' (KST, 시간대 없음) → aware datetime."""
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v)[:19])
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=KST)


def _ok(data: dict) -> dict:
    if str(data.get("code")) not in ("200", "SUCCESS"):
        raise MarketApiError(f"쿠팡 {data.get('code')} {str(data.get('message'))[:120]}")
    return data


async def _coupang_listings() -> list[dict]:
    vendor = await coupang_vendor_id()
    summaries: list[dict] = []
    token = ""
    for _ in range(COUPANG_MAX_PAGES):
        q = {"vendorId": vendor, "maxPerPage": COUPANG_PAGE_SIZE}
        if token:
            q["nextToken"] = token
        data = _ok(await _coupang_get(COUPANG_PRODUCTS_PATH, urllib.parse.urlencode(q)))
        summaries += data.get("data") or []
        token = data.get("nextToken") or ""
        if not token:
            break

    out = []
    for s in summaries:
        spid = str(s.get("sellerProductId") or "")
        if not spid:
            continue
        d = _ok(await _coupang_get(f"{COUPANG_PRODUCTS_PATH}/{spid}", "")).get("data") or {}
        items, code = [], None
        for it in d.get("items") or []:
            m = SKU_RE.match(str(it.get("externalVendorSku") or "").strip())
            if m:
                code = code or m.group(1).upper()
            items.append({
                "option_id": int(m.group(2)) if m and m.group(2) else None,
                "bundle_qty": int(m.group(3)) if m and m.group(3) else 1,
                "name": it.get("itemName"),
                "sale_price": it.get("salePrice"),
                "market_item_id": str(it.get("vendorItemId") or "") or None,
                "sku": it.get("externalVendorSku"),
            })
        product_no = d.get("productId") or s.get("productId")
        first_vi = next((i["market_item_id"] for i in items if i["market_item_id"]), None)
        url = None
        if product_no:
            url = COUPANG_VIEW_URL.format(pid=product_no) + (f"?vendorItemId={first_vi}" if first_vi else "")
        out.append({
            "market_product_id": spid,
            "product_code": code,
            "title": d.get("sellerProductName") or s.get("sellerProductName"),
            "status": d.get("statusName") or s.get("statusName"),
            "listed_at": _parse_kst(s.get("createdAt") or d.get("createdAt")),
            "url": url,
            "items": items,
        })
    return out
