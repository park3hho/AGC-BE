"""배송비 별도형(마트형) 상품 등록 공통 (2026-11-21).

product.shipping_mode == 'separate' 인 제품(낱개)은 박스 상품과 따로 올리고,
- 배송비 9,900원 · 5만 원 무료배송 없음
- 묶음배송: 쿠팡 UNION_DELIVERY(같은 출고지), 네이버 기본 배송비 묶음그룹(57384202, 가장 작은 배송비 1번)
- 검색어 태그: 브랜드 한글 표기 변형 · 병음 · 영문 · 제품 종류 · 일반 키워드 (최소 10개, 한자 없음)
cp_new.py · nv_group.py 가 import 해서 쓴다.
"""

import re

SEPARATE_FEE = 9900
NV_BUNDLE_GROUP = 57384202   # 네이버 '기본 배송비 묶음그룹' (MIN — 묶음 안에서 가장 작은 배송비 한 번)

# 브랜드 → 태그 (한글 표기 변형 · 병음 · 영문). 한자·남의 상표 금지
BRAND_TAGS = {
    "차지": ["차지", "패왕차희", "바왕차지", "CHAGEE", "bawangchaji", "차지티백"],
    "차옌웨써": ["차옌웨써", "차얀위에써", "차안열색", "chayanyuese", "차옌웨써티백"],
    "차리": ["차리", "차리티", "CHALI", "chali", "차리티백"],
    "미쉐빙청": ["미쉐빙청", "미쉐", "밀설빙성", "MIXUE", "mixuebingcheng"],
    "후상아이": ["후상아이", "호상아이", "hushangayi", "후상아이티백"],
    "샤오관차": ["샤오관차", "소관차", "xiaoguancha", "샤오관차티백"],
    "루이싱": ["루이싱", "루이싱커피", "LUCKIN", "luckincoffee", "ruixing"],
    "UHA": ["UHA", "유하", "쿠루루", "미각당", "kululu"],
}

KIND_TAGS = {
    "tea": ["중국차", "티백", "중국티백", "원엽차", "해외직구", "중국직구", "구매대행", "수입차", "차선물", "중국식품"],
    "coffee": ["원두", "원두커피", "커피원두", "홀빈", "싱글오리진", "해외직구", "중국직구", "구매대행", "수입원두", "중국식품"],
    "jelly": ["젤리", "과즙젤리", "중국젤리", "중국간식", "해외직구", "중국직구", "구매대행", "수입젤리", "중국식품", "간식"],
    "other": ["해외직구", "중국직구", "구매대행", "중국식품", "수입식품"],
}

# 맛·종류 키워드 (제목에 있으면 태그로)
KW = ["재스민", "자스민", "우롱", "우롱차", "홍차", "녹차", "룽징", "계화", "복숭아", "리치", "장미", "백차", "보이차", "냉침", "냉침차",
      "과일차", "꽃차", "선물세트", "밀크티", "청포도", "포도", "딸기", "멜론", "체리", "예가체프", "브라질", "케냐", "분말"]


def is_separate(row):
    return (row or {}).get("shipping_mode") == "separate"


def kind_of(title, category):
    if category == "tea":
        return "tea"
    if re.search(r"원두|커피", title or ""):
        return "coffee"
    if re.search(r"젤리|구미|软糖", title or ""):
        return "jelly"
    return "other"


def brand_key(title):
    t = re.sub(r"^\s*\[[^\]]*\]\s*", "", title or "")
    for k in BRAND_TAGS:
        if t.startswith(k):
            return k
    return None


def tags(title, flavor, category, limit):
    """태그 최소 10개: 브랜드 변형 → 맛·종류 키워드 → 일반 키워드. 한자 제거."""
    kind = kind_of(title, category)
    words = list(BRAND_TAGS.get(brand_key(title), []))
    if flavor:
        words += [re.sub(r"\(.*?\)|×\d+|\d+박스", "", f).strip() for f in re.split(r"[+·]", flavor)]
    words += [k for k in KW if k in (title or "") or k in (flavor or "")]
    words += KIND_TAGS[kind]
    out = []
    for w in words:
        w = re.sub(r"[^0-9A-Za-z가-힣]", "", w or "")
        if 1 < len(w) <= 15 and w.lower() not in {o.lower() for o in out}:
            out.append(w)
    return out[:limit]


def unit_total(option2, total):
    """규격 문자열의 실제 수량. parse_spec 은 첫 '3g×8티백' 만 본다 → '×2박스' 곱하기, 'A 4개입 + B 8개' 더하기."""
    s = option2 or ""
    head = s.split("(")[0]
    m = re.search(r"×\s*(\d+)\s*(?:티백|개입|개|봉|스틱)\s*×\s*(\d+)\s*박스", head)
    if m:
        return int(m.group(1)) * int(m.group(2))
    if "+" in head:
        nums = [int(x) for x in re.findall(r"(\d+)\s*(?:개입|개|티백)", head)]
        if len(nums) >= 2:
            return sum(nums)
    return total


def item_name(option2):
    """옵션(아이템) 이름 = 규격 문자열 그대로 (한자 없음)."""
    s = re.sub(r"[\u4e00-\u9fff]+", "", option2 or "")
    return re.sub(r"\s{2,}", " ", s).strip()


def fix_specs(pr):
    """별도형: specs 수량·이름을 규격 문자열 기준으로 고치고 상품명을 '제품명 맛 규격' 으로."""
    pr["specs"] = [(sp, unit_total(r.get("option2"), total), item_name(r.get("option2")) or name, r) for sp, total, name, r in pr["specs"]]
    if pr["specs"]:
        pr["pname"] = f"{pr['title']} {pr['specs'][0][2]}"[:100]
    return pr


def cp_delivery(body):
    """쿠팡: 유료배송 9,900원 · 묶음배송 가능 (출고지 같은 상품끼리)."""
    body.update({"deliveryChargeType": "NOT_FREE", "deliveryCharge": SEPARATE_FEE, "freeShipOverAmount": 0,
                 "deliveryChargeOnReturn": 0, "unionDeliveryType": "UNION_DELIVERY"})
    return body


def nv_delivery(info):
    """네이버 specificProduct/originProduct 의 deliveryInfo 를 유료 9,900원 · 기본 묶음그룹으로."""
    info["deliveryFee"] = {"deliveryFeeType": "PAID", "baseFee": SEPARATE_FEE, "deliveryFeePayType": "PREPAID"}
    info["deliveryBundleGroupUsable"] = True
    info["deliveryBundleGroupId"] = NV_BUNDLE_GROUP
    return info


def food_type(title, category):
    """상품정보고시 '식품의 유형' (네이버 기본값 '음료' 대신)."""
    return {"tea": "침출차", "coffee": "커피(볶은커피)", "jelly": "캤디류(젤리)"}.get(kind_of(title, category), "기타가공품")


def nv_category(title, category):
    """별도형 낱개 상품의 네이버 카테고리 (차 티백은 '차류', 음료 카테고리 아님)."""
    kind = kind_of(title, category)
    if kind == "coffee":
        return 50002266   # 식품>음료>커피>원두/생두
    if kind == "jelly":
        return 50022479   # 식품>젤리/사탕/초콜릿>젤리
    if kind == "tea":
        t = title or ""
        has = {k: (k in t) for k in ("우롱", "홍차", "녹차", "룽징", "재스민", "보이", "백차")}
        kinds = [k for k in ("우롱", "홍차", "녹차") if has[k]] + (["녹차"] if has["룽징"] and not has["녹차"] else [])
        if has["재스민"] and len(set(kinds) - {"녹차", "홍차"}) == 0 and not re.search(r"모음|세트|가지|종", t):
            return 50018600   # 자스민차
        if len(set(kinds)) == 1 and not re.search(r"모음|가지|종\b|5종|7가지|15가지", t):
            return {"우롱": 50013040, "홍차": 50002380, "녹차": 50002268}[kinds[0]]
        return 50002384       # 기타차
    return None
