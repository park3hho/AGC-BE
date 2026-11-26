import re, sys
src = open("/app/scripts/market/cp_new.py", encoding="utf-8").read()
anchor = "from services.product.detail_export_service import jpeg_size, png_size"
assert anchor in src
inject = anchor + r'''

_W = r"(봉|갑|캔|박스|통|병|개|세트)"
def _mk(a, u, c, w):
    u = {"G": "g", "KG": "kg"}.get(u, u)
    if "." in a: a = a.rstrip("0").rstrip(".")
    return {"amt": a, "unit": u, "cnt": int(c), "word": w}
def parse_spec(s):
    full = s or ""; s0 = full.split("(")[0].strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg)\s*[×xX*]\s*(\d+)\s*" + _W, s0)
    if m: return _mk(m[1], m[2], m[3], m[4])
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg)\s*1\s*" + _W, s0)
    if m: return _mk(m[1], m[2], 1, m[3])
    m = re.search(r"1\s*" + _W + r"\s*(\d+(?:\.\d+)?)\s*(g|kg)", s0)
    if m: return _mk(m[2], m[3], 1, m[1])
    m = re.search(r"(\d+)\s*개입\s*(\d+(?:\.\d+)?)\s*(g|kg)", s0)
    if m: return _mk(m[2], m[3], 1, "박스")
    m = re.search(r"병\s*[×x]\s*(\d+)", s0); g = re.search(r"약\s*(\d+)\s*g", full)
    if m and g: return _mk(str(round(int(g[1]) / int(m[1]))), "g", m[1], "병")
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg", s0)
    if m and "斤" in s0: return _mk(m[1], "kg", 1, "박스")
    m = re.search(r"(\d+)\s*" + _W + r"\s*\(?\s*약?\s*(\d+(?:\.\d+)?)\s*(g|kg)", full)
    if m:
        n = int(m[1]); tot = float(m[3])
        if n >= 20: return _mk(m[3], m[4], 1, "세트")
        return _mk(str(round(tot / n)), m[4], n, m[2])
    return None
'''
src = src.replace(anchor, inject, 1)
src = src.replace('GENERIC = ["중국음료", "해외직구", "중국직구", "구매대행", "중국식품", "수입음료", "직구음료", "중국현지음료", "대륙음료", "중국편의점"]',
                  'GENERIC = ["중국과자", "중국간식", "해외직구", "중국직구", "구매대행", "중국식품", "수입과자", "직구과자", "대륙간식", "과자박스"]')
assert "중국과자" in src
assert "if str(cat) not in BEV_OK" in src
src = re.sub(r"if str\(cat\) not in BEV_OK[^:]*:", "if False:", src, count=1)
old = '''_strip_cn0 = strip_cn
def strip_cn(s):'''
assert old in src
src = src.replace(old, old + r'''
    return _despec(_strip_cn1(s))
def _despec(s):
    s = (s or '').replace('왕왕 쌀과자 셴베이·쉐빙', '왕왕 쌀과자')
    for rx in [r"\d+(?:\.\d+)?\s*(?:g|kg)(?:\s*\(\s*\d+\s*봉\s*\))?(?:\s*[×x]\s*\d+\s*[가-힣]*)?", r"\d+\s*개입\s*[×x]\s*\d+\s*박스",
               r"\d+\s*알\s*[×x]\s*\d+\s*병", r"\(\s*약\s*\d+\s*봉\s*\)", r"약\s*\d+\s*봉", r"(?<![0-9가-힣+])\d+\s*(?:갑|봉|캔|통)(?![가-힣])",
               r"×\s*\d+", r"\(\s*맛 선택\s*\)", r"\(\s*\d+\s*개\s*\)", r"\(\s*\)"]:
        s = re.sub(rx, " ", s)
    s = re.sub(r"\s*\+\s*$", "", re.sub(r"\s{2,}", " ", s)).strip(" ·,/")
    return re.sub(r"\s{2,}", " ", s).strip()
def _strip_cn1(s):''', 1)
old = 'prow = (await q(conn, "select photos, category, title_ko from product where id=$1", pid))[0]'
assert old in src
src = src.replace(old, 'prow = (await q(conn, "select photo_url, photos, category, title_ko from product where id=$1", pid))[0]')
old = 'photos = prow["photos"] if isinstance(prow["photos"], list) else json.loads(prow["photos"] or "[]")'
assert old in src
src = src.replace(old, old + '\n            photos = [prow["photo_url"]] + list(photos)')
old = "PCAT = {}"
assert old in src
src = src.replace(old, "PCAT = {417: (59624, '스틱/빼빼로/막대과자'), 421: (59628, '과자쿠키'), 422: (59624, '스틱/빼빼로/막대과자'), 427: (72900, '기타스낵'), 435: (72900, '기타스낵')}", 1)
old = '            tags = make_tags(pr, catname, is_tea)'
assert old in src
src = src.replace(old, """            for it, (sp, total, name, r) in zip(body["items"], pr["specs"]):
                names = {a["attributeTypeName"] for a in it["attributes"]}
                if "농산물 중량" in names and "개당 중량" not in names:
                    it["attributes"].append({"attributeTypeName": "개당 중량", "attributeValueName": f"{sp['amt']}{sp['unit']}"})
""" + old)
old = '            if dry:\n                json.dump(body'
assert old in src
src = src.replace(old, '''            if dry:
                req = [a["attributeTypeName"] for a in m.get("attributes", []) if a.get("required") == "MANDATORY"]
                have = {a["attributeTypeName"] for a in body["items"][0]["attributes"]}
                log("   attrs", [(a["attributeTypeName"], a["attributeValueName"]) for a in body["items"][0]["attributes"]], "| MANDATORY missing:", [x for x in req if x not in have])
                json.dump(body''', 1)
exec(src)



