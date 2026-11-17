import asyncio, json, re, sys, os
sys_argv = list(sys.argv); sys.argv = ["x"]
src = open("/app/scripts/market/cp_base.py").read()
src = src.replace('json.load(open("/private/market/small_imgs.json"))', '[]').replace('/private/market/cp_create.log', '/private/market/cp_new.log')
exec(src.split("async def main(args):")[0])
sys.argv = sys_argv
from services.product.detail_export_service import jpeg_size, png_size

_strip_cn0 = strip_cn
def strip_cn(s):
    s = re.sub(r"^\s*\[[^\]]*\]\s*", "", s or "")
    s = re.sub(r"\(([^)]*)\)", lambda m: "" if re.search(r"\d\s*(ml|mL|g|kg|L)|·|,|×|캔|팩|병", m.group(1)) else m.group(0), s)
    return _strip_cn0(s)

KW_CAT = [(re.compile(r"전해질|스포츠|이온"), (58770, "스포츠/이온음료"))]

GENERIC = ["중국음료", "해외직구", "중국직구", "구매대행", "중국식품", "수입음료", "직구음료", "중국현지음료", "대륙음료", "중국편의점"]
TEA_GENERIC = ["중국차", "티백", "해외직구", "중국직구", "구매대행", "중국식품", "수입차", "직구차", "찻잎", "차선물"]
BAN = {"레드불", "redbull", "RedBull"}
UNIT_WORD = re.compile(r"^\d|ml$|^x$|캔$|병$|팩$|개입$|박스$")

def img_ok(u):
    try:
        b = open("/uploads/" + u[len("/files/"):], "rb").read()
    except Exception:
        return False
    s = jpeg_size(b) or png_size(b)
    return bool(s and s[0] >= 500 and s[1] >= 500)

def pick_photo(pr, prod_photos):
    cands = [pr["photo"]] + list(prod_photos)
    for u in cands:
        if u and img_ok(u):
            return u
    return None

def make_tags(pr, catname, is_tea):
    words = [pr["brand"], strip_cn(pr["flavor"])]
    t = re.sub(r"[\[\]()·,/]", " ", strip_cn(pr["title"]))
    words += [w for w in t.split() if len(w) >= 2 and not UNIT_WORD.search(w)]
    leaf = (catname.split(">")[-1].strip() if catname else "")
    if leaf: words.append(leaf)
    words += [pr["brand"] + (strip_cn(pr["flavor"]) or "")]
    words += (TEA_GENERIC if is_tea else GENERIC)
    out = []
    for w in words:
        w = re.sub(r"[^0-9A-Za-z가-힣]", "", w or "")
        if 1 < len(w) <= 20 and w not in out and w not in BAN:
            out.append(w)
    return out[:20]

LISTED = set()
LISTED_SKUS = set()   # 쿠팡 등록 기록에 있는 sku (add-flavor)
BARCODES = {}
PCAT = {}
BEV_OK = {"58795","58770","72807","111595","58768","72815","58779","72812","72824","58762","58962","58769","58771","58772","58773","58774","58775","58776","58777","58778","58780","72808","72809","72810","72811","72813","72814","72816","72817"}

async def main(args):
    dry = "--dry" in args
    add_flavor = "--add-flavor" in args   # 이미 올린 제품에 새 맛(옵션)만 추가 — 기존 상품은 그대로 (2026-11-18)
    pids = [int(a) for a in args if a.isdigit()]
    await Tortoise.init(config=TORTOISE_ORM)
    conn = Tortoise.get_connection("default")
    for r in await q(conn, "select product_id from market_listing where platform='coupang' and deleted_at is null"):
        LISTED.add(r["product_id"])
    for r in await q(conn, "select x->>'sku' sku from market_listing ml, jsonb_array_elements(ml.items) x where ml.platform='coupang' and ml.deleted_at is null"):
        if r["sku"]: LISTED_SKUS.add(r["sku"])
    for r in await q(conn, "select id, barcode from product_option where deleted_at is null and barcode is not null and barcode <> ''"):
        BARCODES[r["id"]] = r["barcode"].strip()
    for pid in pids:
        if pid in LISTED and not add_flavor:
            log(f"  skip pid {pid} (already listed)"); continue
        try:
            prs = await build_products(conn, pid)
            prow = (await q(conn, "select photos, category from product where id=$1", pid))[0]
            photos = prow["photos"] if isinstance(prow["photos"], list) else json.loads(prow["photos"] or "[]")
            is_tea = prow["category"] == "tea"
        except Exception as e:
            log(f"  ! pid {pid} build error {e}"); continue
        for pr in prs:
            key = f"{pr['code']}|{pr['flavor']}"
            if key in DONE:
                log(f"   skip {key} (done)"); continue
            ph = pick_photo(pr, photos)
            if not ph:
                log(f"  ! {key} no photo >=500px"); continue
            pr["photo"] = ph
            try:
                if pid in PCAT:
                    cat, catname = PCAT[pid]
                elif is_tea:
                    cat, catname = 58874, "기타전통차류"
                else:
                    cat, catname = await predict(pr["pname"])
                    if str(cat) not in BEV_OK:
                        t = pr["title"]
                        if re.search(r"탄산|소다|콜라|스파클링|기포", t): cat, catname = 58768, "기타탄산음료"
                        elif re.search(r"전해질|스포츠|이온", t): cat, catname = 58770, "스포츠/이온음료"
                        elif re.search(r"커피|라테|아메리카노", t): cat, catname = 58795, "커피음료"
                        elif re.search(r"차|티", t): cat, catname = 72815, "기타차음료"
                        else: cat, catname = 72807, "기타 과일/야채 음료"
                        log(f"   category fallback -> {cat} {catname}")
                ov = OVERRIDE.get(catname)
                if ov: cat, catname = ov
                if not is_tea:
                    for rx, cc in KW_CAT:
                        if rx.search(pr["title"]): cat, catname = cc; break
                PCAT[pid] = (cat, catname)
                m = await meta(cat)
            except Exception as e:
                log(f"  ! {key} predict/meta error {str(e)[:200]}"); continue
            food_type = catname.split(">")[-1].strip() if catname else "상품 상세페이지 참조"
            body = payload(pr, cat, m, food_type)
            if is_tea:
                for it, (sp, total, name, r) in zip(body["items"], pr["specs"]):
                    bq = r["bundle_qty"] or 1
                    boxes = max(1, total // sp["cnt"]) if sp["cnt"] else bq
                    it["attributes"] = [{"attributeTypeName": "최소 중량", "attributeValueName": f"{sp['amt']}{sp['unit']}"},
                                         {"attributeTypeName": "개당 수량", "attributeValueName": f"{sp['cnt']}개입"},
                                         {"attributeTypeName": "수량", "attributeValueName": f"{boxes}박스"}]
            tags = make_tags(pr, catname, is_tea)
            for it in body["items"]:
                it["searchTags"] = tags
            if pr["brand"] in BRAND_IDS:
                body["brandId"] = BRAND_IDS[pr["brand"]]
            # 바코드(GTIN): 옵션에 있으면 넣고, 공식 브랜드 상품은 바코드 없는 옵션을 빼서 올린다
            keep = []
            used_bc = set()   # 같은 바코드를 쓰는 옵션(12병·15병 등)은 첫 옵션만 바코드, 나머지는 emptyBarcode (2026-11-17)
            for it in body["items"]:
                mo = re.match(r".*-(\d+)(?:x\d+)?$", it["externalVendorSku"])
                bc = BARCODES.get(int(mo.group(1))) if mo else None
                if bc and bc in used_bc:
                    it["barcode"] = ""; it["emptyBarcode"] = True; it["emptyBarcodeReason"] = "같은 바코드 옵션이 따로 있음"
                    keep.append(it); continue
                if bc:
                    used_bc.add(bc)
                    it["attributes"].append({"attributeTypeName": "Global Trade Item Number", "attributeValueName": bc})
                    if re.search(r"x\d+$", it["externalVendorSku"]):
                        it["barcode"] = ""; it["emptyBarcode"] = True; it["emptyBarcodeReason"] = "묶음 상품(낱개 바코드는 단품 옵션에 등록)"
                    else:
                        it["barcode"] = bc; it["emptyBarcode"] = False; it["emptyBarcodeReason"] = ""
                if bc or not body.get("brandId"):
                    keep.append(it)
            if not keep:
                log(f"  ! {key} skipped: brand product without barcode"); continue
            if add_flavor:   # 이미 쿠팡 등록 기록에 있는 옵션(옵션 id·묶음 수)은 빼고 새 것만
                keep = [it for it in keep if it["externalVendorSku"] not in LISTED_SKUS]
                if not keep:
                    log(f"   skip {key} (add-flavor: all options already listed)"); continue
            body["items"] = keep
            log(f"== {key} {pr['pname']} | cat {cat} {catname} | tags {len(tags)} | " + str([(i['itemName'], i['salePrice'], i['externalVendorSku']) for i in body['items']]))
            if dry:
                json.dump(body, open(f"/private/market/cpnew_{pr['code']}.json", "w"), ensure_ascii=False); continue
            for attempt in range(2):
                try:
                    r = await call("POST", SP, "", body)
                    msg = r.get("message") or ""
                    log(f"   POST {r.get('code')} spid={r.get('data')} {msg[:160]}")
                    if r.get("code") == "SUCCESS" and r.get("data"):
                        DONE.add(key); open("/private/market/cp_done.txt", "a").write(f"{key}|{r.get('data')}\n"); break
                    if attempt == 0 and body["brand"] and not body.get("brandId") and ("브랜드" in msg or "MPN/GTIN" in msg):
                        log("   retry without brand"); body["brand"] = ""; continue
                    break
                except Exception as e:
                    log(f"   ERR {str(e)[:300]}"); break
            await asyncio.sleep(1.0)
    await Tortoise.close_connections()

asyncio.run(main(sys.argv[1:]))
