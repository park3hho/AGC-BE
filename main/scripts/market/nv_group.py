import sys, json, re, asyncio, time
_argv = list(sys.argv)
w = open("/app/scripts/market/nv_new.py", encoding="utf-8").read()
w = w.replace("/private/market/nv_new.log", "/private/market/nv_group.log").replace("/private/market/nv_new_done.txt", "/private/market/nv_group_done_unused.txt")
w = w.replace('exec(head + "async def main(args):" + tail)', 'head = head.replace(\'SKIP = {"PR-261022-0006", "PR-261024-0018", "PR-261025-0022"}\', "SKIP = set()")\nexec(head)')
exec(w)
sys.argv = _argv

CATBY = json.load(open("/app/scripts/market/nv_catmap.json"))
GUIDES = {}

async def guide_for(cat):
    if cat not in GUIDES:
        for i in range(6):
            st, j = await napi("GET", f"/v2/standard-purchase-option-guides?categoryId={cat}")
            if st != 429: break
            await asyncio.sleep(3 + i * 2)
        GUIDES[cat] = j if st == 200 else {}
    return GUIDES[cat]

def pick_guide(g, need_flavor, is_tea=False):
    want = [["맛", "용량", "수량"]] if need_flavor else ([["개당 중량", "개당 수량", "수량"], ["용량", "수량"]] if is_tea else [["용량", "수량"]])
    for wnt in want:
        for x in g.get("optionGuides", []):
            names = [o["optionName"] for o in x["standardPurchaseOptions"]]
            if names == wnt:
                return x
    return None

JUICE = {50002258, 50002259, 50002260, 50002261, 50002262, 50002263, 50002264, 50012840, 50012681, 50012860}
TEAISH = {50012001, 50012240}

def opt_value(o, sp, total, flavor):
    n = o["optionName"]
    if n == "맛": return flavor or "기본"
    if n == "용량":
        units = [u["unit"] for u in o.get("optionUsableUnits") or []]
        unit = sp["unit"]
        if unit not in units and unit == "g" and "ml" in units: unit = "ml"
        if unit not in units and units: unit = units[0]
        return f"{sp['amt']}{unit}"
    if n == "개당 중량": return f"{sp['amt']}{sp['unit'] if sp['unit'] in ('g','kg') else 'g'}"
    if n == "개당 수량": return f"{sp['cnt']}개입"
    if n == "수량": return f"{total}개" if not o.get("_tea") else f"{max(1, total // max(1, sp['cnt']))}개"
    return None

async def build_groups(conn, pid, dry=False):
    prs = await build(conn, pid)
    if not prs: return [(None, "no build")]
    code = prs[0]["code"]
    cat = int(CATBY.get(code) or ncat(code, prs[0]["flavor"])[0])
    is_tea = (await q(conn, "select category from product where id=$1", pid))[0]["category"] == "tea"
    flavors = list(dict.fromkeys(p["flavor"] for p in prs))
    multi = len(flavors) > 1
    g = await guide_for(cat)
    guide = pick_guide(g, multi, is_tea) if g.get("useOptionYn") else None
    if multi and not guide:
        if cat in JUICE: cat = 50002265
        elif cat in TEAISH: cat = 50012002
        g = await guide_for(cat)
        guide = pick_guide(g, True, is_tea) if g.get("useOptionYn") else None
    if guide:
        return [await build_group(conn, prs, flavors, cat, guide, is_tea, dry)]
    # 맛 옵션이 없는 카테고리(차류 등): 맛마다 따로 그룹
    g = await guide_for(cat)
    guide = pick_guide(g, False, is_tea) if g.get("useOptionYn") else None
    if not guide: return [(None, f"category {cat} no usable guide")]
    out = []
    for fl in flavors:
        out.append(await build_group(conn, [p for p in prs if p["flavor"] == fl], [fl], cat, guide, is_tea, dry, per_flavor=True))
    return out

async def build_group(conn, prs, flavors, cat, guide, is_tea, dry=False, per_flavor=False):
    code = prs[0]["code"]
    for o in guide["standardPurchaseOptions"]:
        if is_tea: o["_tea"] = True
    by_fl = {}
    for p in prs:
        by_fl.setdefault(p["flavor"], {"pr": p, "specs": []})["specs"] += p["specs"]
    base_pr = prs[0]
    if per_flavor:
        title = base_pr["title"]
    else:
        title = base_pr["title"]
        for f in sorted((strip_cn(x) for x in flavors), key=len, reverse=True):
            if len(flavors) > 1 and f and f in title and title.replace(f, "").strip():
                title = title.replace(f, "", 1)
        title = re.sub(r"\s{2,}", " ", title).strip()
    title = strip_cn(title)
    det_urls = ["D"] if dry else await upload_images([local(f["url"]) for f in base_pr["files"]])
    html = "".join(f'<img src="{u}" style="width:100%;display:block" />' for u in det_urls)
    specifics = []
    _names = list(dict.fromkeys(strip_cn(f) or "기본" for f in flavors))
    fl_order = {f: _names.index(strip_cn(f) or "기본") + 1 for f in flavors}
    seen = set()
    for fl, d in by_fl.items():
        p = d["pr"]
        rep = "R" if dry else (await upload_images([local(rep_url(p["photo"]))]))[0]
        heavy_any = False
        for sp, total, name, r in sorted(d["specs"], key=lambda x: x[3]["sale_price"]):
            key = (strip_cn(fl), sp["amt"], sp["unit"], total)
            if key in seen: continue
            seen.add(key)
            heavy = sp["unit"] in ("ml", "g") and float(sp["amt"]) * total > 8000 or sp["unit"] in ("L", "kg") and float(sp["amt"]) * total > 8
            opts = []
            for o in guide["standardPurchaseOptions"]:
                v = opt_value(o, sp, total, strip_cn(fl))
                item = {"optionId": o["optionId"], "valueName": v}
                if o["optionName"] in ("수량", "용량", "개당 중량", "개당 수량"): pass
                if o["optionName"] == "맛": item["valueOrder"] = fl_order[fl]
                opts.append(item)
            bq = r["bundle_qty"] or 1
            specifics.append({
                "standardPurchaseOptions": opts,
                "salePrice": r["sale_price"], "stockQuantity": 999,
                "images": {"representativeImage": {"url": rep}},
                "deliveryInfo": {"deliveryType": "DELIVERY", "deliveryAttributeType": "NORMAL", "deliveryCompany": "CJGLS",
                                 "deliveryBundleGroupUsable": False, "deliveryFee": {"deliveryFeeType": "FREE"},
                                 "claimDeliveryInfo": {"returnDeliveryFee": 10000 if heavy else 5000, "exchangeDeliveryFee": 2 * (10000 if heavy else 5000),
                                                       "shippingAddressId": RELEASE, "returnAddressId": RETURN}, "installationFee": False},
                "originAreaInfo": {"originAreaCode": "0200037", "importer": "이도식품 (해외구매대행)"},
                "sellerCodeInfo": {"sellerManagementCode": f"{code}-{r['oid']}" + (f"x{bq}" if bq > 1 else "")},
                "customsTaxType": "NOT_APPLICABLE",
                "unitCapacity": unit_cap({"specs": [(sp, total, name, r)]}),
                "_meta": {"flavor": fl, "name": name, "oid": r["oid"], "bq": bq, "code": code, "price": r["sale_price"], "vals": [x["valueName"] for x in opts]},
            })
    words = [base_pr["brand"]] + [strip_cn(f) for f in flavors] + [w for w in re.sub(r"[\[\]()·,/]", " ", title).split() if len(w) >= 2 and not re.search(r"^\d|ml$|캔$|병$|팩$|개입$", w)] + ["중국음료", "해외직구", "중국직구", "구매대행"]
    tags = []
    for t in words:
        t = re.sub(r"[^0-9A-Za-z가-힣]", "", t or "")
        if 1 < len(t) <= 15 and t not in tags and t != "레드불": tags.append(t)
    pr_notice = dict(base_pr); pr_notice["specs"] = sorted(sum((d["specs"] for d in by_fl.values()), []), key=lambda x: x[3]["sale_price"])[:6]
    pr_notice["notice_title"] = title
    nt = notice(pr_notice, "")
    for k, v in list(nt.get("generalFood", {}).items()):
        if isinstance(v, str) and k != "customerServicePhoneNumber":
            nt["generalFood"][k] = re.sub(r"\s{2,}", " ", re.sub(r"[^0-9A-Za-z가-힣\s,.()%/+\-:×]", " ", v)).strip() or "상품 상세페이지 참조"
    gname = title if len(title) < 40 else re.sub(r"\s*\([^)]*\)", "", title).strip()
    if len(gname) >= 40: gname = gname[:39].rstrip()
    gp = {"leafCategoryId": str(cat), "name": gname, "guideId": guide["guideId"],
          "brandName": base_pr["brand"], "manufacturerName": base_pr["brand"],
          "taxType": "TAX", "saleType": "NEW", "minorPurchasable": True,
          "productInfoProvidedNotice": nt,
          "afterServiceInfo": {"afterServiceTelephoneNumber": "010-2560-1411", "afterServiceGuideContent": "상품 상세페이지 참조"},
          "seoInfo": {"sellerTags": [{"text": t} for t in tags[:10]]},
          "commonDetailContent": html,
          "specificProducts": specifics,
          "smartstoreGroupChannel": {"naverShoppingRegistration": True, "channelProductDisplayStatusType": "ON"}}
    return gp, None

def strip_meta(gp):
    g = json.loads(json.dumps(gp))
    for s in g["specificProducts"]:
        s.pop("_meta", None)
        s["smartstoreChannelProduct"] = {"naverShoppingRegistration": True, "channelProductDisplayStatusType": "ON"}
    return g

async def submit(gp):
    for attempt in range(5):
        st, j = await napi("POST", "/v2/standard-group-products", {"groupProduct": strip_meta(gp)})
        if st == 429: await asyncio.sleep(3 + attempt * 2); continue
        inv = j.get("invalidInputs") or []
        bad_tags = [x for x in inv if "sellerTags" in x.get("name", "") or "Tags" in x.get("type", "") or "태그" in x.get("message", "")]
        if st == 400 and bad_tags and attempt < 4:
            idxs = {int(m.group(1)) for x in bad_tags for m in [re.search(r"sellerTags\[(\d+)\]", x.get("name", ""))] if m}
            words = [w.strip().replace("태그명:", "").strip() for x in bad_tags for g in re.findall(r"\(([^)]+)\)", x.get("message", "")) for w in g.split(",") if w.strip()]
            words = [w for w in words if w]
            if not words and not idxs: return st, j
            tg = gp["seoInfo"]["sellerTags"]
            gp["seoInfo"]["sellerTags"] = [t for i, t in enumerate(tg) if i not in idxs and not any(w.lower() in t["text"].lower() for w in words)]
            continue
        return st, j
    return st, j

async def status(req_id=None):
    for path in [f"/v2/standard-group-products/status?type=CREATE&requestId={req_id}", f"/v2/standard-group-products/status?type=CREATE"]:
        st, j = await napi("GET", path)
        if st != 404: return st, j
    return st, j

async def main(args):
    dry = "--dry" in args
    pids = [int(a) for a in args if a.isdigit()]
    await Tortoise.init(config=TORTOISE_ORM)
    conn = Tortoise.get_connection("default")
    for pid in pids:
      for gi, (gp, err) in enumerate(await build_groups(conn, pid, dry)):
        if err:
            nlog(f"!! pid {pid} {err}"); continue
        nlog(f"== pid {pid} {gp['name']} | cat {gp['leafCategoryId']} guide {gp['guideId']} | {len(gp['specificProducts'])} items: " + str([(s['_meta']['name'], s['_meta']['flavor'], s['salePrice']) for s in gp['specificProducts']]))
        if dry:
            json.dump(strip_meta(gp), open(f"/private/market/grp_dry_{pid}_{gi}.json", "w"), ensure_ascii=False); continue
        st, j = await submit(gp)
        nlog(f"   POST {st} {json.dumps(j, ensure_ascii=False)[:600]}")
        json.dump({"pid": pid, "gi": gi, "st": st, "resp": j, "items": [s["_meta"] for s in gp["specificProducts"]], "name": gp["name"], "cat": gp["leafCategoryId"]}, open(f"/private/market/grp_post_{pid}_{gi}.json", "w"), ensure_ascii=False)
        await asyncio.sleep(1)
    await Tortoise.close_connections()

async def wait_status(req_id):
    import urllib.parse
    for i in range(40):
        await asyncio.sleep(3)
        st, j = await napi("GET", f"/v2/standard-group-products/status?type=CREATE&requestId={urllib.parse.quote(req_id)}")
        stt = (j.get("progress") or {}).get("state")
        if stt in ("COMPLETED", "FAILED", "ERROR"): return stt, j
    return "TIMEOUT", j

PENDING = "/private/market/nv_pending.txt"   # pid|gi|requestId — 보냈지만 결과 확인 전


def load_pending():
    if not os.path.exists(PENDING): return {}
    out = {}
    for l in open(PENDING):
        p = l.strip().split("|")
        if len(p) == 3: out[f"{p[0]}|{p[1]}"] = p[2]
    return out


def save_pending(pid, gi, req):
    open(PENDING, "a").write(f"{pid}|{gi}|{req}\n")


def drop_pending(pid, gi):
    if not os.path.exists(PENDING): return
    keep = [l for l in open(PENDING) if not l.startswith(f"{pid}|{gi}|")]
    open(PENDING, "w").write("".join(keep))


async def migrate(args):
    from datetime import datetime, timezone
    pids = [int(a) for a in args if a.isdigit()]
    await Tortoise.init(config=TORTOISE_ORM)
    conn = Tortoise.get_connection("default")
    add_flavor = "--add-flavor" in args   # 기존 그룹·상품은 그대로 두고, 아직 안 올린 옵션만 새 그룹으로 (2026-11-18, 제품 24·43 사례)
    done = {l.split("|")[0] for l in open("/private/market/grp_migrated.txt")} if os.path.exists("/private/market/grp_migrated.txt") else set()
    pend = load_pending()
    for pid in pids:
        if str(pid) in done and not add_flavor: continue
        groups = await build_groups(conn, pid)
        if add_flavor:
            listed = {r["sku"] for r in await q(conn, "select x->>'sku' sku from market_listing ml, jsonb_array_elements(ml.items) x where ml.platform='naver' and ml.deleted_at is null and ml.product_id=$1", pid)}
            kept = []
            for gp, err in groups:
                if err: kept.append((gp, err)); continue
                gp["specificProducts"] = [s for s in gp["specificProducts"] if s["sellerCodeInfo"]["sellerManagementCode"] not in listed]
                if gp["specificProducts"]: kept.append((gp, None))
            groups = kept
            if not groups:
                nlog(f"   pid {pid} add-flavor: nothing new"); continue
        if any(err for _, err in groups):
            nlog(f"!! pid {pid} " + "; ".join(err for _, err in groups if err)); continue
        made = []
        ok = True
        for gi, (gp, _) in enumerate(groups):
            meta = [s["_meta"] for s in gp["specificProducts"]]
            # 등록은 한 번만 — 전에 보내고 결과를 못 받은 요청이 있으면 다시 POST 하지 않고 그 결과를 본다 (중복 그룹 버그, 2026-11-17)
            req = pend.get(f"{pid}|{gi}")
            if not req:
                st, j = await submit(gp)
                if st != 200 or not j.get("requestId"):
                    nlog(f"!! pid {pid} g{gi} POST {st} {json.dumps(j, ensure_ascii=False)[:400]}"); ok = False; break
                req = j["requestId"]
                save_pending(pid, gi, req); pend[f"{pid}|{gi}"] = req
            stt, r = await wait_status(req)
            if stt != "COMPLETED":
                # TIMEOUT 이면 pending 에 남겨 두고 다음 실행 때 상태만 다시 본다 (재 POST 금지). FAILED 면 지운다
                if stt in ("FAILED", "ERROR"): drop_pending(pid, gi); pend.pop(f"{pid}|{gi}", None)
                nlog(f"!! pid {pid} g{gi} {stt} req {req} {json.dumps(r, ensure_ascii=False)[:600]}"); ok = False; break
            drop_pending(pid, gi); pend.pop(f"{pid}|{gi}", None)
            made.append((gp, meta, r))
            nlog(f"== pid {pid} g{gi} group {r.get('groupProductNo')} {gp['name']} ({len(meta)} items)")
        if not ok:
            continue
        # 예전 개별 상품 지우기 (add-flavor 면 지우지 않는다)
        olds = [] if add_flavor else await q(conn, "select id, market_product_id, memo from market_listing where platform='naver' and product_id=$1 and deleted_at is null", pid)
        chs = [int(o["market_product_id"]) for o in olds]
        orig = {}
        for i in range(0, len(chs), 20):
            st, j = await napi("POST", "/v1/products/search", {"searchKeywordType": "CHANNEL_PRODUCT_NO", "channelProductNos": chs[i:i+20], "page": 1, "size": 50})
            for c in j.get("contents", []):
                for x in c["channelProducts"]: orig[str(x["channelProductNo"])] = c["originProductNo"]
        deleted = 0
        for o in olds:
            on = orig.get(o["market_product_id"])
            if on:
                for a in range(4):
                    st, j = await napi("DELETE", f"/v2/products/origin-products/{on}")
                    if st != 429: break
                    await asyncio.sleep(3)
                if st != 200:
                    nlog(f"   ! delete old {o['market_product_id']} {st} {json.dumps(j, ensure_ascii=False)[:200]}"); continue
            await conn.execute_query("delete from market_listing where id=$1", [o["id"]]); deleted += 1
            await asyncio.sleep(0.4)
        # AGC 기록: 그룹 안 상품 하나당 한 줄
        for gp, meta, r in made:
            ids = {p["originProductNo"]: p["smartstoreChannelProductNo"] for p in r.get("productNos", [])}
            vals = {x["originProductNo"]: " ".join(v["valueName"] for v in x["standardPurchaseOptionsIds"]) for x in r.get("standardPurchaseOptionsIds", [])}
            for on, ch in ids.items():
                label = vals.get(on, "")
                m = next((mm for mm in meta if " ".join(mm["vals"]) == label), None)
                if not m:
                    nlog(f"   ? no meta match for {on} '{label}'"); m = meta[0]
                await conn.execute_query(
                    "insert into market_listing (product_id, platform, market_product_id, title, url, status, listed_at, items, source, memo, created_at, updated_at) values ($1,'naver',$2,$3,$4,'판매중',now(),$5::jsonb,'api',$6,now(),now())",
                    [pid, str(ch), f"{gp['name']} {label}"[:200], f"https://smartstore.naver.com/eidofood/products/{ch}",
                     json.dumps([{"sku": f"{m['code']}-{m['oid']}" + (f"x{m['bq']}" if m['bq'] > 1 else ""), "name": label, "option_id": m["oid"], "bundle_qty": m["bq"], "sale_price": m["price"], "market_item_id": None}], ensure_ascii=False),
                     f"group {r.get('groupProductNo')} originProductNo {on}"])
        open("/private/market/grp_migrated.txt", "a").write(f"{pid}|" + ",".join(str(r.get('groupProductNo')) for _, _, r in made) + f"|deleted {deleted}\n")
        nlog(f"   migrated pid {pid}: groups {[r.get('groupProductNo') for _, _, r in made]}, old deleted {deleted}/{len(olds)}")
    await Tortoise.close_connections()

import os
if "--migrate" in sys.argv:
    asyncio.run(migrate(sys.argv[1:]))
else:
    asyncio.run(main(sys.argv[1:]))
