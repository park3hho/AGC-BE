import asyncio, json, copy, re, sys, urllib.request, urllib.error
from tortoise import Tortoise
from services.order.market_clients import _naver_auth, NAVER_BASE
GROUPS=[int(x) for x in sys.argv[1].split(",")]
APPLY="--apply" in sys.argv
def req(method,url,h,body=None):
    r=urllib.request.Request(url,data=body,method=method,headers=h)
    try:
        with urllib.request.urlopen(r,timeout=90) as x: return x.status,json.loads(x.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
async def m():
    from database import TORTOISE_ORM
    await Tortoise.init(config=TORTOISE_ORM); c=Tortoise.get_connection("default")
    p2={x['option_id']:x['sale_price'] for x in await c.execute_query_dict("select op.option_id, op.sale_price from option_price op join product_pricing pp on pp.id=op.pricing_id where pp.platform='naver' and pp.product_id in (452,453,454) and op.bundle_qty=2")}
    tk=await _naver_auth(); h={"Authorization":f"Bearer {tk}","Content-Type":"application/json"}
    for g in GROUPS:
        s,j=await asyncio.to_thread(req,"GET",NAVER_BASE+f"/v2/standard-group-products/{g}",h)
        gp=j["groupProduct"]; sp=gp["specificProducts"]; codes={x["sellerCodeInfo"]["sellerManagementCode"] for x in sp}; new=[]
        for x in sp:
            code=x["sellerCodeInfo"]["sellerManagementCode"]; mo=re.match(r"^PR-\d{6}-[0-9A-F]{4}-(\d+)$", code)
            if not mo or int(mo.group(1)) not in p2 or code+"x2" in codes: continue
            n=copy.deepcopy(x); n.pop("originProductNo",None); n.pop("smartstoreChannelProductNo",None)
            for k in list(n.keys()):
                if k.endswith("ChannelProductNo"): n.pop(k)
            last=n["standardPurchaseOptions"][-1]
            last["valueName"]=re.sub(r"(\d+)", lambda m_: str(int(m_.group(1))*2), last["valueName"],count=1)
            n["productName"]=re.sub(r"(\d+)개$", lambda m_: f"{int(m_.group(1))*2}개", n["productName"])
            n["salePrice"]=p2[int(mo.group(1))]
            n["sellerCodeInfo"]["sellerManagementCode"]=code+"x2"
            new.append(n)
        orders={}
        for x in sp:
            for o in x["standardPurchaseOptions"]:
                orders.setdefault(o["optionId"],{})[o["valueName"]]=o["valueOrder"]
        for n in new:
            for o in n["standardPurchaseOptions"]:
                d=orders.setdefault(o["optionId"],{})
                if o["valueName"] not in d: d[o["valueName"]]=max(d.values() or [0])+1
                o["valueOrder"]=d[o["valueName"]]
        print(g, "new", [(n["productName"], n["salePrice"], n["standardPurchaseOptions"][-1]["valueName"]) for n in new])
        if not APPLY or not new: continue
        gp["specificProducts"]=sp+new
        s2,j2=await asyncio.to_thread(req,"PUT",NAVER_BASE+f"/v2/standard-group-products/{g}",h,json.dumps({"groupProduct":gp},ensure_ascii=False).encode())
        print(g, "PUT", s2, json.dumps(j2,ensure_ascii=False)[:400])
        open("/private/market/nv_bundle_put.txt","a").write(f"{g}|{s2}|{json.dumps(j2,ensure_ascii=False)[:300]}\n")
asyncio.run(m())
