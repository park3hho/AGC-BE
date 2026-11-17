import re, sys, json
src = open("/app/scripts/market/nv_base.py").read()
src = src.replace('open("/app/scripts/market/cp_base.py").read()', 'open("/app/scripts/market/cp_base.py").read().replace(\'json.load(open("/private/market/small_imgs.json"))\', "[]").replace("/private/market/cp_create.log", "/private/market/cp_nvhelper.log")')
src = src.replace('/private/market/nv_create.log', '/private/market/nv_new.log').replace('/private/market/nv_done.txt', '/private/market/nv_new_done.txt')
# categories from the Coupang run of this batch
src = src.replace('for l in open("/private/market/cp_create.log"):\n        m = re.match(r"== (\\S+) \\[(.*?)\\] .*? \\| cat (\\d+) (.*?) \\| brand", l)\n        if m:\n            out[f"{m.group(1)}|{m.group(2)}"] = m.group(4).strip()',
                  'for l in open("/private/market/cp_new.log", encoding="utf-8"):\n        m = re.match(r"== (PR-\\S+?)\\|(.*?) \\| cat (\\d+) (.*?) \\| tags", l)\n        if m:\n            out[m.group(1)] = m.group(4).strip()')
assert 'cp_new.log' in src
src = src.replace('n = CPCAT.get(f"{code}|{flavor}", "")', 'n = CPCAT.get(code, "")\n    if code in TEA_CAT: return TEA_CAT[code], "차류"')
src = src.replace('DEFAULT_CAT = 50002265', 'DEFAULT_CAT = 50002265\nCATMAP.update({"기타 과일/야채 음료": 50002265, "야채혼합주스": 50002265, "국산탄산수": 50002033, "사과즙": 50002260, "기타건강음료": 50012041, "일반두유": 50012800, "기타차음료": 50012002, "스포츠/이온음료": 50002256})\nTEA_CAT = {}')
# cleaner titles (drop "(550ml, 자몽·레몬)" style parentheses and leading [티백])
src = src.replace('from services.order.market_clients import _naver_auth, NAVER_BASE',
 'from services.order.market_clients import _naver_auth, NAVER_BASE\n_s0 = strip_cn\ndef strip_cn(s):\n    s = re.sub(r"^\\s*\\[[^\\]]*\\]\\s*", "", s or "")\n    s = re.sub(r"\\(([^)]*)\\)", lambda m: "" if re.search(r"\\d\\s*(ml|mL|g|kg|L)|·|,|×|캔|팩|병", m.group(1)) else m.group(0), s)\n    return _s0(s)')
# more tags (Naver: max 10, <=15 chars)
src = src.replace('tags = [re.sub(r"[^0-9A-Za-z가-힣]", "", t) for t in [pr["brand"], strip_cn(pr["flavor"]), "중국음료", "해외직구", "중국직구", "구매대행"]]',
 'words = [pr["brand"], strip_cn(pr["flavor"])] + [w for w in re.sub(r"[\\[\\]()·,/]", " ", pr["title"]).split() if len(w) >= 2 and not re.search(r"^\\d|ml$|캔$|병$|팩$|개입$", w)] + (["중국차", "티백", "해외직구", "중국직구", "구매대행", "수입차"] if pr["code"] in TEA_CAT else ["중국음료", "해외직구", "중국직구", "구매대행", "수입음료", "중국편의점"])\n    tags = [re.sub(r"[^0-9A-Za-z가-힣]", "", t) for t in words]')
src = src.replace('if 1 < len(t) <= 15][:10]', 'if 1 < len(t) <= 15 and t not in ("레드불",)][:10]')
head, tail = src.rsplit("async def main(args):", 1)
tail = tail.replace('    for pid in pids:\n        try: prs = await build(conn, pid)',
 '    listed = {r["product_id"] for r in await q(conn, "select product_id from market_listing where platform=\'naver\'")}\n    SUB = {"puer": 50002382, "oolong": 50013040, "green": 50002268, "black": 50002380, "jasmine": 50018600, "herbal": 50002381, "flower": 50013100}\n    for r in await q(conn, "select code, subcategory from product where category=\'tea\'"):\n        TEA_CAT[r["code"]] = SUB.get(r["subcategory"], 50002384)\n    for pid in pids:\n        if pid in listed: nlog(f"  skip pid {pid} (listed)"); continue\n        try: prs = await build(conn, pid)')
exec(head + "async def main(args):" + tail)
