import asyncio, json, re, sys, copy
from collections import OrderedDict
from tortoise import Tortoise
from database import TORTOISE_ORM
from services.order.market_clients import _coupang_call, _coupang_get

PUB = "https://api.eidofood.com"
SP = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
TEMPLATE = json.load(open("/app/scripts/market/cp_template.json"))
SPEC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|L|l|g|G|kg|KG)\s*[×xX*]\s*(\d+)\s*([가-힣A-Za-z]+)?")
HAN = re.compile(r"[\u4e00-\u9fff]")
UNIT = {"ml": "ml", "mL": "ml", "ML": "ml", "L": "L", "l": "L", "g": "g", "G": "g", "kg": "kg", "KG": "kg"}
_meta = {}
# 예측 카테고리가 어색한 경우 바꿈 (전해질수→이온음료, 과일우유→기타맛우유, 완제 주스→기타 과일음료)
OVERRIDE = {"기타생수": (58770, "스포츠/이온음료"), "국산생수": (58770, "스포츠/이온음료"),
            "기타다이어트식품": (72950, "기타맛우유"), "환자영양식": (72950, "기타맛우유"),
            "농축액/원액": (72807, "기타 과일/야채 음료"), "비타민음료": (72812, "아이스티음료"),
            "요거트 파우더": (105921, "떠먹는 요구르트")}
LOG = open("/private/market/cp_create.log", "a")
# Wing 브랜드 관리에서 '내 브랜드'로 등록한 브랜드
BRAND_IDS = {"미닛메이드": "KR-69232", "코카콜라": "KR-68961", "스타벅스": "KR-27618", "ARCTICOCEAN": "KR-133534",
             "농부산천": "KR-69617", "오리온": "KR-68537"}
# 냉개 바코드(EAN-13) — 확인된 것만. 공식 브랜드 상품은 쿠팡이 GTIN 을 요구한다
GTINS = {"PR-261022-0006|과립 오렌지": "6975682480058"}
SMALL = {u for u, _ in json.load(open("/private/market/small_imgs.json"))}


def rep_url(u):
    # 쿠팡 대표이미지는 최소 500×500 — 작은 사진은 흰 여백을 더한 _sq 판을 쓴다
    if u in SMALL:
        return u.rsplit(".", 1)[0] + "_sq.jpg"
    return u


try:
    DONE = {"|".join(l.strip().split("|")[:2]) for l in open("/private/market/cp_done.txt") if l.strip()}
except FileNotFoundError:
    DONE = set()


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s); LOG.write(s + "\n"); LOG.flush()


async def q(conn, s, *a):
    return await conn.execute_query_dict(s, list(a) if a else None)


W_ONLY = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|L|l|g|G|kg|KG)(?![A-Za-z])")
def parse_spec(s):
    m = SPEC_RE.search(s or "")
    if not m:
        w = W_ONLY.search(s or "")   # 무게만 있는 옵션 (예: 120g, 357g 병차) — 1개로 본다 (2026-10-31)
        if not w:
            return None
        amt, unit = w.groups()
        if "." in amt:
            amt = amt.rstrip("0").rstrip(".")
        return {"amt": amt, "unit": UNIT[unit], "cnt": 1, "word": "개"}
    amt, unit, cnt, word = m.groups()
    if "." in amt:
        amt = amt.rstrip("0").rstrip(".")
    return {"amt": amt, "unit": UNIT[unit], "cnt": int(cnt), "word": word or "개"}


from utils.option_spec import spec_dict as _spec_dict   # 규격 구조 칸 (2026-11-22)


def option_spec(r):
    """옵션 행 → (sp, 옵션 1개의 총 개수). product_option 구조 칸(unit_amount · total_count …)이 있으면 그것,
    비어 있으면 예전처럼 parse_spec(option2). 구조 칸에서 온 sp 에는 "total" 이 있다."""
    sp = _spec_dict(r)
    if sp:
        return sp, sp["total"]
    sp = parse_spec(r.get("option2"))
    return (sp, sp["cnt"]) if sp else (None, None)


def spec_name(sp, total, r):
    """아이템 이름 "3g×16티백". 섞인 구성(과일칩 4개입 + 티백 3g×8개)은 규격 글자 그대로 (+ 묶음이면 ×N)."""
    if sp.get("mixed"):
        bq = r.get("bundle_qty") or 1
        name = re.sub(r"\s{2,}", " ", re.sub(r"[\u4e00-\u9fff]+", "", r.get("option2") or "")).strip()
        return f"{name} ×{bq}" if bq > 1 else name
    return f"{sp['amt']}{sp['unit']}×{total}{sp['word']}"


def clean(v):
    v = re.sub(r"\[\[[^\]]*\]\]", "", v or "").strip(" ,·/")
    return v or "상품 상세페이지 참조"


def nutrition_text(content):
    info = content.get("info") or {}
    n = [f"{x.get('label')} {x.get('value')}" for x in (info.get("nutrition") or []) if x.get("value") and "[[" not in x.get("value")]
    if not n:
        return "상품 상세페이지 참조"
    note = info.get("note") or ""
    base = "100ml당 " if "100ml" in note else ("100g당 " if "100g" in note else "")
    return base + ", ".join(n) + " (현지 라벨 기준, 상세페이지 참조)"


async def call(method, path, query="", body=None):
    for i in range(6):
        try:
            return await _coupang_call(method, path, query, body)
        except Exception as e:
            if "429" in str(e) and i < 5:
                await asyncio.sleep(2 + i * 2); continue
            raise


def strip_cn(s):
    s = re.sub(r"\([^)]*[\u4e00-\u9fff][^)]*\)", "", s or "")
    s = HAN.sub("", s)
    return re.sub(r"\s{2,}", " ", s).strip()


async def predict(name):
    r = await call("POST", "/v2/providers/openapi/apis/api/v1/categorization/predict", "", {"productName": name})
    d = r.get("data") or {}
    return int(d.get("predictedCategoryId")), d.get("predictedCategoryName") or ""


async def meta(code):
    if code not in _meta:
        r = await call("GET", f"/v2/providers/seller_api/apis/api/v1/marketplace/meta/category-related-metas/display-category-codes/{code}", "")
        _meta[code] = r.get("data") or {}
    return _meta[code]


def build_attrs(m, sp, total):
    out = []
    for a in m.get("attributes", []):
        if a.get("exposed") != "EXPOSED":
            continue
        n = a["attributeTypeName"]
        if "용량" in n and sp["unit"] in ("ml", "L"):
            out.append({"attributeTypeName": n, "attributeValueName": f"{sp['amt']}{sp['unit']}"})
        elif "중량" in n and sp["unit"] in ("g", "kg"):
            out.append({"attributeTypeName": n, "attributeValueName": f"{sp['amt']}{sp['unit']}"})
        elif n in ("총 수량", "수량"):
            units = a.get("usableUnits") or []
            u = "개" if (not units or "개" in units) else units[0]
            out.append({"attributeTypeName": n, "attributeValueName": f"{total}{u}"})
    return out


def build_notices(m, title, im, spec_text, content, food_type):
    cats = m.get("noticeCategories", [])
    cat = next((c for c in cats if c["noticeCategoryName"] == "가공식품"), None) \
        or next((c for c in cats if "식품" in c["noticeCategoryName"]), None) or (cats[0] if cats else None)
    if not cat:
        return []
    bm = im.get("브랜드 · 제조사", "")
    mm = re.search(r"\(([^)]*)\)", bm)
    mfr = mm.group(1) if mm else bm
    val = {
        "제품명": title,
        "식품의 유형": food_type,
        "생산자 및 소재지": f"{clean(mfr)} / {clean(im.get('원산지') or '중국')}",
        "제조연월일, 소비기한 또는 품질유지기한": clean(im.get("소비기한")) + " (상세페이지 참조)",
        "포장단위별 내용물의 용량(중량), 수량": spec_text,
        "원재료명 및 함량": clean(im.get("원재료")) + " (현지 라벨 기준, 상세페이지 참조)",
        "영양성분": nutrition_text(content),
        "유전자변형식품에 해당하는 경우의 표시": "해당없음",
        "소비자안전을 위한 주의사항": "상품 상세페이지 참조",
        "수입식품 문구": "해외구매대행 상품 (수입식품등 인터넷 구매대행업 등록번호 20260028639)",
        "소비자상담관련 전화번호": "010-2560-1411",
    }
    return [{"noticeCategoryName": cat["noticeCategoryName"], "noticeCategoryDetailName": d["noticeCategoryDetailName"],
             "content": val.get(d["noticeCategoryDetailName"], "상품 상세페이지 참조")} for d in cat.get("noticeCategoryDetailNames", [])]


async def build_products(conn, pid):
    p = (await q(conn, "select id, code, title_ko, photo_url from product where id=$1", pid))[0]
    dp = (await q(conn, "select id, content, status from detail_page where product_id=$1", pid))[0]
    if dp["status"] != "approved":
        log(f"  ! {p['code']} not approved"); return []
    content = dp["content"] if isinstance(dp["content"], dict) else json.loads(dp["content"])
    ex = await q(conn, "select files from detail_page_export where page_id=$1 and platform='coupang' order by version desc limit 1", dp["id"])
    if not ex:
        log(f"  ! {p['code']} no coupang export"); return []
    files = ex[0]["files"] if isinstance(ex[0]["files"], list) else json.loads(ex[0]["files"])
    rows = await q(conn, """select o.id oid, o.option1, o.option2, o.photo_url, op.sale_price, op.bundle_qty,
        o.unit_amount, o.unit, o.unit_count, o.count_word, o.pack_count, o.total_count
        from option_price op join product_pricing pp on pp.id=op.pricing_id join product_option o on o.id=op.option_id and o.deleted_at is null
        where pp.product_id=$1 and pp.platform='coupang' and op.sale_price is not null order by o.id, op.bundle_qty""", pid)
    im = {r.get("label", ""): (r.get("value") or "") for r in ((content.get("info") or {}).get("rows") or [])}
    title_ko = strip_cn(p["title_ko"])
    brand = re.split(r"[\s(]", title_ko)[0]
    hero_sub = ((content.get("hero") or {}).get("name_sub") or "").split("·")[0].strip()
    groups = OrderedDict()
    for r in rows:
        groups.setdefault((r["option1"] or "").strip(), []).append(r)
    all_flavors = [strip_cn(f) for f in groups if f]
    out = []
    for flavor, rs in groups.items():
        specs = []
        for r in rs:
            sp, per = option_spec(r)
            if not sp:
                log(f"  ! {p['code']} spec parse fail: {r['option2']}"); continue
            total = per * (r["bundle_qty"] or 1)
            specs.append((sp, total, spec_name(sp, total, r), r))
        if not specs:
            continue
        # sort by total count
        specs.sort(key=lambda x: (x[0]["amt"], x[1]))
        sp0 = specs[0][0]
        counts = "/".join(dict.fromkeys(f"{t}{s['word']}" for s, t, _, _ in specs))
        title = title_ko
        flavor = strip_cn(flavor)
        # 제품명에 다른 맛 이름이 들어 있으면 이 맛으로 바꾼다 (예: '오렌지꿀맛 스포츠음료' 의 레몬꿀맛)
        if flavor and flavor not in title:
            other = next((o for o in sorted(all_flavors, key=len, reverse=True) if o != flavor and len(o) >= 2 and o in title), None)
            if other:
                title = title.replace(other, flavor, 1)
        if flavor and flavor not in title:
            title = f"{title} {flavor}"
        amts = list(dict.fromkeys(f"{s['amt']}{s['unit']}" for s, _, _, _ in specs))
        pname = f"{title} {'/'.join(amts)} x {counts}"[:100]
        out.append({"pid": pid, "code": p["code"], "flavor": flavor, "pname": pname, "title": title, "brand": brand,
                    "photo": next((x[3]["photo_url"] for x in specs if x[3]["photo_url"]), None) or p["photo_url"],
                    "files": files, "content": content, "im": im, "specs": specs,
                    "notice_title": f"{title} ({hero_sub})" if hero_sub and HAN.search(hero_sub) else title})
    return out


def payload(pr, cat_code, m, food_type):
    keys = ("vendorId", "saleEndedAt", "deliveryMethod", "deliveryCompanyCode", "deliveryChargeType", "deliveryCharge",
            "freeShipOverAmount", "deliveryChargeOnReturn", "remoteAreaDeliverable", "unionDeliveryType", "returnCenterCode",
            "returnChargeName", "companyContactNumber", "returnZipCode", "returnAddress", "returnAddressDetail", "exchangeType",
            "outboundShippingPlaceCode", "vendorUserId")
    body = {k: copy.deepcopy(TEMPLATE[k]) for k in keys}
    mm = re.search(r"\(([^)]*)\)", pr["im"].get("브랜드 · 제조사", ""))
    heavy = any(s["unit"] in ("ml", "g") and float(s["amt"]) * t > 8000 or s["unit"] in ("L", "kg") and float(s["amt"]) * t > 8 for s, t, _, _ in pr["specs"])
    body.update({"displayCategoryCode": cat_code, "sellerProductName": pr["pname"], "displayProductName": pr["pname"],
                 "brand": pr["brand"], "generalProductName": pr["title"][:100], "productGroup": "",
                 "saleStartedAt": "2026-10-26T00:00:00", "returnCharge": 10000 if heavy else 5000,
                 "afterServiceInformation": "상품 상세페이지 참조", "afterServiceContactNumber": "010-2560-1411",
                 "manufacture": clean(mm.group(1) if mm else pr["brand"]), "requested": True,
                 "requiredDocuments": [], "extraInfoMessage": ""})
    tags = [re.sub(r"[^0-9A-Za-z가-힣]", "", t) for t in [pr["brand"], pr["flavor"], "중국음료", "해외직구", "중국직구", "구매대행"]]
    tags = [t for t in dict.fromkeys(tags) if 1 < len(t) <= 20][:20]
    contents = [{"contentsType": "IMAGE_NO_SPACE", "contentDetails": [{"content": PUB + f["url"], "detailType": "IMAGE"} for f in pr["files"]]}]
    base = {k: v for k, v in TEMPLATE["items"][0].items() if k in (
        "offerCondition", "offerDescription", "maximumBuyCount", "maximumBuyForPerson", "outboundShippingTimeDay",
        "maximumBuyForPersonPeriod", "adultOnly", "taxType", "parallelImported", "overseasPurchased", "pccNeeded",
        "emptyBarcode", "emptyBarcodeReason", "barcode", "saleAgentCommission", "modelNo", "certifications")}
    items = []
    for sp, total, name, r in pr["specs"]:
        bq = r["bundle_qty"] or 1
        it = copy.deepcopy(base)
        it.update({"itemName": name, "originalPrice": r["sale_price"], "salePrice": r["sale_price"], "unitCount": total,
                   "externalVendorSku": f"{pr['code']}-{r['oid']}" + (f"x{bq}" if bq > 1 else ""), "searchTags": tags,
                   "images": [{"imageOrder": 0, "imageType": "REPRESENTATION", "vendorPath": PUB + rep_url(pr["photo"])}],
                   "attributes": build_attrs(m, sp, total), "contents": contents,
                   "notices": build_notices(m, pr["notice_title"], pr["im"], name if sp.get("mixed") else f"{sp['amt']}{sp['unit']} × {total}{sp['word']}", pr["content"], food_type)})
        items.append(it)
    body["items"] = items
    return body


async def main(args):
    dry = "--dry" in args
    pids = [int(a) for a in args if a.isdigit()]
    await Tortoise.init(config=TORTOISE_ORM)
    conn = Tortoise.get_connection("default")
    for pid in pids:
        try:
            prs = await build_products(conn, pid)
        except Exception as e:
            log(f"  ! pid {pid} build error {e}"); continue
        for pr in prs:
            try:
                cat, catname = await predict(pr["pname"])
                ov = OVERRIDE.get(catname)
                if ov:
                    cat, catname = ov
                m = await meta(cat)
            except Exception as e:
                log(f"  ! {pr['code']} predict/meta error {str(e)[:200]}"); continue
            food_type = catname.split(">")[-1].strip() if catname else "상품 상세페이지 참조"
            body = payload(pr, cat, m, food_type)
            log(f"== {pr['code']} [{pr['flavor']}] {pr['pname']} | cat {cat} {catname} | brand {pr['brand']} | "
                + str([(i['itemName'], i['salePrice'], i['externalVendorSku'], [a['attributeValueName'] for a in i['attributes']]) for i in body['items']]))
            if dry:
                json.dump(body, open(f"/private/market/cpnew_{pr['code']}.json", "w"), ensure_ascii=False)
                continue
            if pr["brand"] in BRAND_IDS:
                body["brandId"] = BRAND_IDS[pr["brand"]]
            g = GTINS.get(f"{pr['code']}|{pr['flavor']}")
            if g:
                for it in body["items"]:
                    it["attributes"].append({"attributeTypeName": "Global Trade Item Number", "attributeValueName": g})
            key = f"{pr['code']}|{pr['flavor']}"
            if key in DONE:
                log(f"   skip (done)"); continue
            if "--nobrand" in args:
                body["brand"] = ""
            for attempt in range(2):
                try:
                    r = await call("POST", SP, "", body)
                    msg = r.get("message") or ""
                    log(f"   POST {r.get('code')} spid={r.get('data')} {msg[:100]}")
                    if r.get("code") == "SUCCESS" and r.get("data"):
                        DONE.add(key); open("/private/market/cp_done.txt", "a").write(f"{key}|{r.get('data')}\n")
                        break
                    if attempt == 0 and body["brand"] and not body.get("brandId") and ("브랜드" in msg or "MPN/GTIN" in msg):
                        log("   retry without brand"); body["brand"] = ""; continue
                    break
                except Exception as e:
                    log(f"   ERR {str(e)[:300]}"); break
            await asyncio.sleep(0.4 if dry else 1.0)
    await Tortoise.close_connections()

asyncio.run(main(sys.argv[1:]))
