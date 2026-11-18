import asyncio, json, copy, re, sys
from tortoise import Tortoise
from services.order.market_clients import _coupang_get, _coupang_call
from services.product import listing_service as ls
ONLY=sys.argv[1] if len(sys.argv)>1 else None
async def m():
    from database import TORTOISE_ORM
    await Tortoise.init(config=TORTOISE_ORM); c=Tortoise.get_connection("default")
    p2={x['option_id']:x['sale_price'] for x in await c.execute_query_dict("select op.option_id, op.sale_price from option_price op join product_pricing pp on pp.id=op.pricing_id where pp.platform='coupang' and pp.product_id in (452,453,454) and op.bundle_qty=2")}
    spids=[x['market_product_id'] for x in await c.execute_query_dict("select market_product_id from market_listing where platform='coupang' and product_id in (452,453,454) and deleted_at is null order by product_id, market_product_id")]
    for spid in spids:
        if ONLY and spid!=ONLY: continue
        d=ls._ok(await _coupang_get(f"{ls.COUPANG_PRODUCTS_PATH}/{spid}","")).get("data") or {}
        skus={i["externalVendorSku"] for i in d["items"]}; new=[]
        for it in d["items"]:
            s=it["externalVendorSku"]; mo=re.match(r"^PR-\d{6}-[0-9A-F]{4}-(\d+)$", s)
            if not mo: continue
            oid=int(mo.group(1))
            if oid not in p2 or s+"x2" in skus: continue
            n=copy.deepcopy(it)
            for k in ("sellerProductItemId","vendorItemId","itemId"): n.pop(k,None)
            n["itemName"]=re.sub(r"(\d+)봉", lambda m_: f"{int(m_.group(1))*2}봉", it["itemName"])
            n["unitCount"]=(it.get("unitCount") or 1)*2
            n["salePrice"]=n["originalPrice"]=p2[oid]
            n["externalVendorSku"]=s+"x2"
            n["barcode"]=""; n["emptyBarcode"]=True; n["emptyBarcodeReason"]="묶음 상품(낱개 바코드는 단품 옵션에 등록)"
            for a in n.get("attributes") or []:
                if a["attributeTypeName"]=="수량" and a.get("attributeValueName"):
                    a["attributeValueName"]=re.sub(r"(\d+)", lambda m_: str(int(m_.group(1))*2), a["attributeValueName"],1)
            new.append(n)
        if not new: print(spid, "nothing"); continue
        body=copy.deepcopy(d); body["items"]=d["items"]+new; body["requested"]=True
        try:
            r=await _coupang_call("PUT", ls.COUPANG_PRODUCTS_PATH, "", body)
            print(spid, "PUT", r.get("code"), str(r.get("message"))[:120], [(x["itemName"],x["salePrice"]) for x in new])
        except Exception as e:
            print(spid, "ERR", str(e)[:300])
        await asyncio.sleep(1)
asyncio.run(m())
