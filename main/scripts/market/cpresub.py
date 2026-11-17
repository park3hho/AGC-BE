import asyncio, sys, json
sys.path.insert(0, "/app")
from services.order.market_clients import _coupang_call
from services.product import listing_service as ls
SP = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
async def main(ids):
    for spid in ids:
        d = ls._ok(await ls._coupang_get(f"{ls.COUPANG_PRODUCTS_PATH}/{spid}", "")).get("data") or {}
        d["requested"] = True
        r = await _coupang_call("PUT", SP, "", d)
        print(spid, r.get("code"), (r.get("message") or "")[:300])
asyncio.run(main(sys.argv[1:]))
