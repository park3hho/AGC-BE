import asyncio, re
from datetime import datetime, timezone
from tortoise import Tortoise
from database import TORTOISE_ORM
from services.product import listing_service as ls
from models.product.listing import MarketListing
from models.product.product import Product
async def main():
    await Tortoise.init(config=TORTOISE_ORM)
    spids = [l.strip().split("|")[-1] for l in open("/private/market/cp_done.txt") if l.strip()]
    now = datetime.now(timezone.utc); made = 0; miss = []
    for spid in spids:
        if await MarketListing.get_or_none(platform="coupang", market_product_id=spid):
            continue
        for i in range(5):
            try:
                d = ls._ok(await ls._coupang_get(f"{ls.COUPANG_PRODUCTS_PATH}/{spid}", "")).get("data") or {}; break
            except Exception as e:
                if "429" in str(e): await asyncio.sleep(2 + i * 2); continue
                raise
        items, code = [], None
        for it in d.get("items") or []:
            m = ls.SKU_RE.match(str(it.get("externalVendorSku") or "").strip())
            if m: code = code or m.group(1).upper()
            items.append({"option_id": int(m.group(2)) if m and m.group(2) else None, "bundle_qty": int(m.group(3)) if m and m.group(3) else 1,
                          "name": it.get("itemName"), "sale_price": it.get("salePrice"),
                          "market_item_id": str(it.get("vendorItemId") or "") or None, "sku": it.get("externalVendorSku")})
        p = await Product.get_or_none(code=code, deleted_at=None)
        if not p: miss.append(spid); continue
        pno = d.get("productId"); vi = next((i["market_item_id"] for i in items if i["market_item_id"]), None)
        url = ls.COUPANG_VIEW_URL.format(pid=pno) + (f"?vendorItemId={vi}" if vi else "") if pno else None
        await MarketListing.create(platform="coupang", market_product_id=spid, product_id=p.id, title=d.get("sellerProductName"),
                                   url=url, status=d.get("statusName"), listed_at=ls._parse_kst(d.get("createdAt")) or now,
                                   items=items, source="api", synced_at=now)
        made += 1
        await asyncio.sleep(0.3)
    print("created", made, "missing", miss)
    await Tortoise.close_connections()
asyncio.run(main())
