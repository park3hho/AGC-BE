import asyncio, json, re, sys, os, uuid, urllib.request, urllib.error, time
from collections import OrderedDict
sys_argv = list(sys.argv)
sys.argv = ["x"]
src = open("/app/scripts/market/cp_base.py").read().split("async def main(args):")[0]
exec(src)  # helpers: q, parse_spec, clean, strip_cn, nutrition_text, rep_url, HAN, PUB, log(cp)
sys.argv = sys_argv
from services.order.market_clients import _naver_auth, NAVER_BASE

NLOG = open("/private/market/nv_create.log", "a")
def nlog(*a):
    s = " ".join(str(x) for x in a); print(s); NLOG.write(s + "\n"); NLOG.flush()

RELEASE, RETURN = 200689931, 200689936
SKIP = {"PR-261022-0006", "PR-261024-0018", "PR-261025-0022"}
CATMAP = {
    "기타차음료": 50012002, "녹차음료": 50012001, "홍차/밀크티음료": 50012001, "아이스티음료": 50002255,
    "커피음료": 50002605, "기타탄산음료": 50002257, "콜라": 50002254, "수입탄산수": 50002033,
    "기타생수": 50002032, "국산생수": 50002032, "스포츠/이온음료": 50002256,
    "오렌지주스": 50002259, "사과주스": 50002260, "망고주스": 50002261, "자몽주스": 50002262,
    "토마토주스": 50002263, "포도주스": 50002264,
    "기타두유": 50012800, "일반두유": 50012800, "귀리/오트두유": 50012800,
    "흰우유": 50012741, "멸균 흰우유": 50012741, "딸기우유": 50012741, "기타맛우유": 50012741, "초코우유": 50012741,
    "마시는 요구르트": 50012742, "떠먹는 요구르트": 50012742, "유산균음료": 50012742,
    "기타건강음료": 50012041, "비타민음료": 50012041, "에너지음료": 50012160,
    "옥수수차음료": 50012240, "보리차음료": 50012240,
}
DEFAULT_CAT = 50002265  # 기타과즙음료 for juice-like leftovers

def cp_cats():
    out = {}; cur = None
    for l in open("/private/market/cp_create.log"):
        m = re.match(r"== (\S+) \[(.*?)\] .*? \| cat (\d+) (.*?) \| brand", l)
        if m:
            out[f"{m.group(1)}|{m.group(2)}"] = m.group(4).strip()
    return out
CPCAT = cp_cats()

def ncat(code, flavor):
    n = CPCAT.get(f"{code}|{flavor}", "")
    if n in CATMAP: return CATMAP[n], n
    if "차" in n: return 50012002, n
    return DEFAULT_CAT, n

TOKEN = {"v": None, "t": 0}
async def token():
    if not TOKEN["v"] or time.time() - TOKEN["t"] > 1800:
        TOKEN["v"] = await _naver_auth(); TOKEN["t"] = time.time()
    return TOKEN["v"]

def _req(method, url, headers, body):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except Exception: return e.code, {}

async def napi(method, path, body=None, raw=None, ctype="application/json"):
    for i in range(6):
        tk = await token()
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        st, j = await asyncio.to_thread(_req, method, NAVER_BASE + path, {"Authorization": f"Bearer {tk}", "Content-Type": ctype}, data)
        if st == 429 and i < 5:
            await asyncio.sleep(2 + 2 * i); continue
        return st, j

async def upload_images(local_paths):
    urls = []
    for i in range(0, len(local_paths), 10):
        b = uuid.uuid4().hex; parts = []
        for p in local_paths[i:i + 10]:
            ext = p.rsplit(".", 1)[-1].lower(); ct = "image/png" if ext == "png" else "image/jpeg"
            parts.append(f"--{b}\r\nContent-Disposition: form-data; name=\"imageFiles\"; filename=\"{os.path.basename(p)}\"\r\nContent-Type: {ct}\r\n\r\n".encode() + open(p, "rb").read() + b"\r\n")
        raw = b"".join(parts) + f"--{b}--\r\n".encode()
        st, j = await napi("POST", "/v1/product-images/upload", raw=raw, ctype=f"multipart/form-data; boundary={b}")
        if st != 200: raise RuntimeError(f"image upload {st} {json.dumps(j, ensure_ascii=False)[:300]}")
        urls += [x["url"] for x in j.get("images", [])]
    return urls

def local(u): return "/uploads/" + u[len("/files/"):]

async def build(conn, pid):
    p = (await q(conn, "select id, code, title_ko, photo_url from product where id=$1", pid))[0]
    if p["code"] in SKIP: return []
    dp = (await q(conn, "select id, content, status from detail_page where product_id=$1", pid))[0]
    content = dp["content"] if isinstance(dp["content"], dict) else json.loads(dp["content"])
    ex = await q(conn, "select files from detail_page_export where page_id=$1 and platform='naver' order by version desc limit 1", dp["id"])
    if not ex: nlog(f"  ! {p['code']} no naver export"); return []
    files = ex[0]["files"] if isinstance(ex[0]["files"], list) else json.loads(ex[0]["files"])
    rows = await q(conn, """select o.id oid, o.option1, o.option2, o.photo_url, op.sale_price, op.bundle_qty
        from option_price op join product_pricing pp on pp.id=op.pricing_id join product_option o on o.id=op.option_id and o.deleted_at is null
        where pp.product_id=$1 and pp.platform='naver' and op.sale_price is not null order by o.id, op.bundle_qty""", pid)
    im = {r.get("label", ""): (r.get("value") or "") for r in ((content.get("info") or {}).get("rows") or [])}
    title_ko = strip_cn(p["title_ko"]); brand = re.split(r"[\s(]", title_ko)[0]
    hero_sub = ((content.get("hero") or {}).get("name_sub") or "").split("·")[0].strip()
    groups = OrderedDict()
    for r in rows: groups.setdefault((r["option1"] or "").strip(), []).append(r)
    all_fl = [strip_cn(f) for f in groups if f]
    out = []
    for flavor_raw, rs in groups.items():
        specs = []
        for r in rs:
            sp = parse_spec(r["option2"])
            if not sp: nlog(f"  ! {p['code']} spec fail {r['option2']}"); continue
            total = sp["cnt"] * (r["bundle_qty"] or 1)
            specs.append((sp, total, f"{sp['amt']}{sp['unit']}×{total}{sp['word']}", r))
        if not specs: continue
        # 같은 이름 규격 중복 제거 (싼 것 유지)
        seen = {}
        for s in sorted(specs, key=lambda x: x[3]["sale_price"]):
            seen.setdefault(s[2], s)
        specs = sorted(seen.values(), key=lambda x: x[3]["sale_price"])
        flavor = strip_cn(flavor_raw)
        title = title_ko
        if flavor and flavor not in title:
            other = next((o for o in sorted(all_fl, key=len, reverse=True) if o != flavor and len(o) >= 2 and o in title), None)
            if other: title = title.replace(other, flavor, 1)
        if flavor and flavor not in title: title = f"{title} {flavor}"
        # 대표 = 최저가, 범위(±50%, 1만원 미만은 -50%~+100%) 넘으면 새 상품
        parts = []
        for s in specs:
            price = s[3]["sale_price"]
            if parts:
                base = parts[-1][0][3]["sale_price"]
                hi = base * (1.0 if base < 10000 else 0.5)
                if price - base <= hi:
                    parts[-1].append(s); continue
            parts.append([s])
        for gi, grp in enumerate(parts):
            counts = "/".join(dict.fromkeys(f"{t}{s['word']}" for s, t, _, _ in grp))
            amts = list(dict.fromkeys(f"{s['amt']}{s['unit']}" for s, _, _, _ in grp))
            pname = f"{title} {'/'.join(amts)} x {counts}"[:100]
            out.append({"pid": pid, "code": p["code"], "flavor": flavor_raw, "group": gi, "pname": pname, "title": title, "brand": brand,
                        "photo": next((x[3]["photo_url"] for x in grp if x[3]["photo_url"]), None) or p["photo_url"],
                        "files": files, "content": content, "im": im, "specs": grp,
                        "notice_title": f"{title} ({hero_sub})" if hero_sub and HAN.search(hero_sub) else title})
    return out

def unit_cap(pr):
    s, t = pr["specs"][0][0], pr["specs"][0][1]
    amt = float(s["amt"]); unit = s["unit"]
    if unit == "L": amt, unit = amt * 1000, "ml"
    if unit == "kg": amt, unit = amt * 1000, "g"
    total = round(amt * t, 1)
    return {"unitPriceYn": True, "totalCapacityValue": int(total) if total == int(total) else total,
            "unitCapacity": 100, "indicationUnit": unit}

def notice(pr, food_type):
    im = pr["im"]; bm = im.get("브랜드 · 제조사", ""); mm = re.search(r"\(([^)]*)\)", bm)
    mfr = clean(mm.group(1) if mm else bm)
    sp, total = pr["specs"][0][0], pr["specs"][0][1]
    return {"productInfoProvidedNoticeType": "GENERAL_FOOD", "generalFood": {
        "productName": pr["notice_title"][:100], "foodType": food_type or "음료",
        "producer": mfr[:100], "location": clean(im.get("원산지") or "중국"),
        "packDateText": "제품 라벨 별도 표기", "consumptionDateText": (clean(im.get("소비기한")) + " (상세페이지 참조)")[:100],
        "weight": " / ".join(f"{s['amt']}{s['unit']} × {t}{s['word']}" for s, t, _, _ in pr["specs"])[:100],
        "amount": " / ".join(f"{t}{s['word']}" for s, t, _, _ in pr["specs"])[:100],
        "ingredients": (clean(im.get("원재료")) + " (현지 라벨 기준, 상세페이지 참조)")[:1000],
        "nutritionFacts": nutrition_text(pr["content"])[:1000],
        "geneticallyModified": False,
        "consumerSafetyCaution": "상품 상세페이지 참조",
        "importDeclarationCheck": False,
        "customerServicePhoneNumber": "010-2560-1411"}}

async def payload(pr, rep_url_nv, detail_urls):
    cat, catname = ncat(pr["code"], pr["flavor"])
    base = pr["specs"][0]; base_price = base[3]["sale_price"]
    heavy = any(s["unit"] in ("ml", "g") and float(s["amt"]) * t > 8000 or s["unit"] in ("L", "kg") and float(s["amt"]) * t > 8 for s, t, _, _ in pr["specs"])
    combos = []
    for s, t, name, r in pr["specs"]:
        bq = r["bundle_qty"] or 1
        combos.append({"optionName1": name[:25], "stockQuantity": 999, "price": r["sale_price"] - base_price,
                       "sellerManagerCode": f"{pr['code']}-{r['oid']}" + (f"x{bq}" if bq > 1 else ""), "usable": True})
    html = "".join(f'<img src="{u}" style="width:100%;display:block" />' for u in detail_urls)
    tags = [re.sub(r"[^0-9A-Za-z가-힣]", "", t) for t in [pr["brand"], strip_cn(pr["flavor"]), "중국음료", "해외직구", "중국직구", "구매대행"]]
    tags = [{"text": t} for t in dict.fromkeys(tags) if 1 < len(t) <= 15][:10]
    body = {"originProduct": {
        "statusType": "SALE", "saleType": "NEW", "leafCategoryId": str(cat), "name": pr["pname"],
        "detailContent": html,
        "images": {"representativeImage": {"url": rep_url_nv}},
        "salePrice": base_price, "stockQuantity": 999 * len(combos),
        "deliveryInfo": {
            "deliveryType": "DELIVERY", "deliveryAttributeType": "NORMAL", "deliveryCompany": "CJGLS",
            "deliveryBundleGroupUsable": False,
            "deliveryFee": {"deliveryFeeType": "FREE"},
            "claimDeliveryInfo": {"returnDeliveryFee": 10000 if heavy else 5000, "exchangeDeliveryFee": 2 * (10000 if heavy else 5000),
                                  "shippingAddressId": RELEASE, "returnAddressId": RETURN},
            "installationFee": False},
        "detailAttribute": {
            "afterServiceInfo": {"afterServiceTelephoneNumber": "010-2560-1411", "afterServiceGuideContent": "상품 상세페이지 참조"},
            "originAreaInfo": {"originAreaCode": "0200037", "importer": "이도식품 (해외구매대행)"},
            "sellerCodeInfo": {"sellerManagementCode": f"{pr['code']}-g{pr['group']}"},
            "optionInfo": {"optionCombinationSortType": "CREATE", "optionCombinationGroupNames": {"optionGroupName1": "규격"},
                           "optionCombinations": combos, "useStockManagement": True},
            "unitCapacity": unit_cap(pr),
            "customsTaxType": "NOT_APPLICABLE",
            "minorPurchasable": True,
            "taxType": "TAX",
            "productInfoProvidedNotice": notice(pr, catname.split(">")[-1] if catname else ""),
            "seoInfo": {"sellerTags": tags},
        }},
        "smartstoreChannelProduct": {"naverShoppingRegistration": True, "channelProductDisplayStatusType": "ON"}}
    return body, cat, catname

try:
    DONE = {"|".join(l.strip().split("|")[:3]) for l in open("/private/market/nv_done.txt") if l.strip()}
except FileNotFoundError:
    DONE = set()

async def main(args):
    dry = "--dry" in args
    pids = [int(a) for a in args if a.isdigit()]
    await Tortoise.init(config=TORTOISE_ORM)
    conn = Tortoise.get_connection("default")
    for pid in pids:
        try: prs = await build(conn, pid)
        except Exception as e: nlog(f"  ! pid {pid} build {e}"); continue
        for pr in prs:
            key = f"{pr['code']}|{pr['flavor']}|{pr['group']}"
            if key in DONE: nlog(f"   skip {key}"); continue
            try:
                if dry:
                    body, cat, catname = await payload(pr, "REP", ["D1"])
                else:
                    rep = await upload_images([local(rep_url(pr["photo"]))])
                    det = await upload_images([local(f["url"]) for f in pr["files"]])
                    body, cat, catname = await payload(pr, rep[0], det)
            except Exception as e:
                nlog(f"   ERR prep {key} {str(e)[:300]}"); continue
            nlog(f"== {key} {pr['pname']} | cat {cat} ({catname}) | " + str([(c['optionName1'], c['price'], c['sellerManagerCode']) for c in body['originProduct']['detailAttribute']['optionInfo']['optionCombinations']]) + f" base {body['originProduct']['salePrice']}")
            if dry:
                json.dump(body, open("/private/market/nv_dry.json", "w"), ensure_ascii=False); continue
            for attempt in range(4):
                st, j = await napi("POST", "/v2/products", body)
                bad = [x for x in (j.get("invalidInputs") or []) if x.get("type") == "Restricted.sellerTags"]
                inv = j.get("invalidInputs") or []
                long_tags = [x for x in inv if x.get("type") == "MaxByteLength" and "sellerTags[" in x.get("name", "")]
                spec = [x for x in inv if str(x.get("type", "")).startswith("SpecialChar") and "productInfoProvidedNotice" in x.get("name", "")]
                if st == 400 and (long_tags or spec) and not bad:
                    da = body["originProduct"]["detailAttribute"]
                    if long_tags:
                        idxs = {int(re.search(r"sellerTags\[(\d+)\]", x["name"]).group(1)) for x in long_tags}
                        da["seoInfo"]["sellerTags"] = [t for i, t in enumerate(da["seoInfo"]["sellerTags"]) if i not in idxs]
                        nlog(f"   drop long tags {sorted(idxs)}")
                    for x in spec:
                        parts = x["name"].split(".")
                        node = body
                        for ptn in parts[:-1]:
                            node = node[ptn]
                        node[parts[-1]] = re.sub(r"\s{2,}", " ", re.sub(r"[^0-9A-Za-z가-힣\s,.()%/+\-:]", " ", node[parts[-1]])).strip()
                        nlog(f"   sanitize {parts[-1]}")
                    continue
                if st == 400 and bad:
                    words = [w.strip() for g in re.findall(r"\(([^)]+)\)", " ".join(x.get("message", "") for x in bad)) for w in g.split(",") if w.strip()]
                    tg = body["originProduct"]["detailAttribute"]["seoInfo"]["sellerTags"]
                    body["originProduct"]["detailAttribute"]["seoInfo"]["sellerTags"] = [x for x in tg if not any(w in x["text"] for w in words)]
                    nlog(f"   drop tags {words}"); continue
                break
            if st == 200 and j.get("originProductNo"):
                nlog(f"   OK origin={j.get('originProductNo')} channel={j.get('smartstoreChannelProductNo')}")
                open("/private/market/nv_done.txt", "a").write(f"{key}|{j.get('originProductNo')}|{j.get('smartstoreChannelProductNo')}\n")
                DONE.add(key)
            else:
                nlog(f"   FAIL {st} {json.dumps(j, ensure_ascii=False)[:900]}")
            await asyncio.sleep(1.0)
    await Tortoise.close_connections()

asyncio.run(main(sys.argv[1:]))
