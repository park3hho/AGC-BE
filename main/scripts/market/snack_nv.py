import sys, re, json
src = open("/app/scripts/market/nv_group.py", encoding="utf-8").read()
cp = open("/app/scripts/market/snack_cp.py", encoding="utf-8").read()
# parse_spec / _despec 정의를 snack_cp.py 에서 가져온다
spec_def = cp.split("inject = anchor + r'''", 1)[1].split("'''", 1)[0]
desp = cp.split("src = src.replace(old, old + r'''", 1)[1].split("''', 1)", 1)[0]
desp_fn = "def _despec(s):" + desp.split("def _despec(s):", 1)[1].split("def _strip_cn1(s):", 1)[0]
anchor = "CATBY = json.load(open(\"/app/scripts/market/nv_catmap.json\"))"
assert anchor in src
inject = spec_def + "\n" + desp_fn + r'''
_nvs0 = strip_cn
def strip_cn(s):
    return _despec(_nvs0(s))
FLFIX = {"말차2+헤이즐넛2+밀크2+팥2+버터1+딸기1": "6가지 맛 혼합"}
_notice0 = notice
def notice(pr, ft):
    return _notice0(pr, ft or CPCAT.get(pr["code"], "") or "과자")
from services.product.detail_export_service import jpeg_size, png_size
def _img_ok(u):
    try:
        b = open("/uploads/" + u[len("/files/"):], "rb").read()
    except Exception:
        return False
    s = jpeg_size(b) or png_size(b)
    return bool(s and s[0] >= 500 and s[1] >= 500)
_build0 = build
async def build(conn, pid):
    prs = await _build0(conn, pid)
    pp = (await q(conn, "select photo_url from product where id=$1", pid))[0]["photo_url"]
    for p in prs:
        if p["brand"] == "세":
            p["brand"] = "세 마리 다람쥐"
        if p["brand"] == "중국":
            p["brand"] = p["title"].split()[1]
        if not (p["photo"] and _img_ok(p["photo"])):
            p["photo"] = pp
        p["flavor"] = FLFIX.get(strip_cn(p["flavor"]), p["flavor"])
    return prs
'''
src = src.replace(anchor, inject + anchor, 1)
cats = {412: 50022699, 413: 50022500, 414: 50022500, 415: 50022659, 416: 50022500, 417: 50022739, 418: 50022739, 419: 50022699,
        420: 50022479, 421: 50022679, 422: 50022739, 423: 50022679, 424: 50022679, 425: 50022679, 426: 50022679, 427: 50022500,
        428: 50022739, 429: 50022500, 430: 50022500, 431: 50022659, 432: 50022739, 433: 50022679, 434: 50022679, 435: 50022500,
        436: 50022500, 437: 50022500, 438: 50022459,
        448: 50022659, 449: 50022739, 450: 50022679, 451: 50022500, 452: 50022500, 453: 50022500, 454: 50022500,
        # 2026-11-25 신규 (파이 50022659 · 쿠키/비스킷 50022679 · 과자세트 50022699 · 기타과자 50022739)
        546: 50022659, 549: 50022659, 576: 50022659, 550: 50022679, 552: 50022679, 553: 50022679, 554: 50022679,
        551: 50022699, 557: 50022699, 567: 50022699, 580: 50022699, 581: 50022699, 583: 50022699, 584: 50022699, 590: 50022659, 600: 50022739}
src = src.replace('GUIDES = {}', 'GUIDES = {}\nCATBY_PID = ' + json.dumps({str(k): v for k, v in cats.items()}), 1)
old = 'cat = int(CATBY.get(code) or ncat(code, prs[0]["flavor"])[0])'
assert old in src
src = src.replace(old, 'cat = int(CATBY_PID.get(str(pid)) or CATBY.get(code) or ncat(code, prs[0][\"flavor\"])[0])')   # 새 제품(별도형 낱개)은 mart.nv_category 가 덮어씀
old = 'want = [["맛", "용량", "수량"]] if need_flavor else'
assert old in src
src = src.replace(old, 'want = [["맛", "용량", "수량"], ["맛", "중량", "수량"]] if need_flavor else ([["용량", "수량"], ["중량", "수량"]] if not is_tea else None) or')
old = '    if n == "용량":'
assert old in src
src = src.replace(old, '    if n == "중량": return f"{sp[\'amt\']}{sp[\'unit\'] if sp[\'unit\'] in (\'g\',\'kg\') else \'g\'}"\n' + old)
old = 'if n == "맛": return flavor or "기본"'
assert old in src
src = src.replace(old, 'if n == "맛": return _fv(flavor)')
src = """
def _fv(f):
    import re as _re
    s = (f or "기본").replace("×", "x").replace("·", "/")
    if len(s) > 20: s = _re.sub(r"\\s*\\([^)]*\\)", "", s)
    s = _re.sub(r"[^0-9A-Za-z가-힣 \\-_+/().,]", " ", s)
    s = _re.sub(r"\\s{2,}", " ", s).strip()
    return s[:20].strip()
""" + src
old = '["중국음료", "해외직구", "중국직구", "구매대행"]'
assert old in src
src = src.replace(old, '["중국과자", "중국간식", "해외직구", "구매대행"]')
old = '    gname = title if len(title) < 40 else'
assert old in src
src = src.replace(old, '    title = {"PR-261115-0002": "오이시(상하오자) 새우칩 스낵", "PR-261115-0009": "량핀푸쯔 버터 타오수", "PR-261117-0008": "하오츠뎬 고섬유 통곡물 비스킷 박스", "PR-261125-0007": "오리온 중국판 초코파이 박스", "PR-261125-000A": "오리온 중국판 코코아 파이 박스", "PR-261125-0025": "오리온 중국판 파이 12개입 5종", "PR-261125-001C": "오레오 취둬둬 소포장 대용량", "PR-261125-0012": "오레오 7가지 맛 선물상자", "PR-261125-0029": "글리코 과자 선물상자 루피 콜라보 포장", "PR-261125-002A": "글리코 과자 선물세트 폼폼푸린 콜라보 포장", "PR-261125-002C": "글리코 과자 선물상자 산리오 캐릭터즈 콜라보 포장", "PR-261125-002D": "글리코 과자 선물상자 헬로키티 콜라보 포장", "PR-261125-003D": "글리코 빼빼로 오흑오홍 곡물 초코 선물상자"}.get(code, title)\n' + old)
dry = "--dry" in sys.argv
pids = [a for a in sys.argv[1:] if a.isdigit()]
extra = [a for a in sys.argv[1:] if a == "--add-flavor"]
sys.argv = ["nv_group.py"] + (["--dry"] if dry else ["--migrate"]) + extra + pids
exec(compile(src, "snack_nv", "exec"))



