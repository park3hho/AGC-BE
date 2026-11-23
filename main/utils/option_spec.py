"""옵션2(규격) 글자 → 구조 칸 (2026-11-22). product_option 의 unit_amount · unit · unit_count · count_word ·
pack_count · total_count · spec_note 를 채운다. 마켓 등록(scripts/market)·배송비(services/pricing/shipping_service)는
이 칸을 먼저 쓰고, 비어 있을 때만 예전 글자 해석(utils/volume.parse_volume_ml · cp_base.parse_spec)으로 돌아간다.

    parse_option_spec("330ml×24캔")                 → 330 ml × 24캔, 묶음 1, 총 24
    parse_option_spec("3g×8티백×2박스")               → 3 g × 8티백, 묶음 2, 총 16     (괄호 밖 "×N박스" 는 곱하기)
    parse_option_spec("3g×18개입 (2박스)")            → 3 g × 18개입, 총 18           (괄호 속은 설명 — 18 이 이미 총 개수)
    parse_option_spec("과일칩 냉침차 4개입 + 티백 3g×8개(24g)") → 3 g × 8개, 총 12 (섞인 구성은 개수를 더한다)
    parse_option_spec("35.8g×2봉 (1갑)")             → 35.8 g × 2봉, 총 2, 설명 "1갑"
    parse_option_spec("1갑 (2소포)")                 → 무게 없음, 1갑, 총 1, 설명 "2소포"
    parse_option_spec("10갑 (약 460g, 상자 …)")       → 46 g × 10갑 (괄호 속 총 무게 ÷ 개수, 과자 parse_spec 과 같은 규칙)
    parse_option_spec("375g 1통 (2통 묶음 750g, …)")  → 375 g × 1통, 설명 "2통 묶음 750g, …"
    parse_option_spec("복숭아맛")                     → 칸 전부 None (못 읽음 — docs/option-spec-review.md 에 남긴다)

g·kg 는 무게, ml·L 는 용량. 배송비는 1g = 1ml 로 본다 (2026-10-24 사용자 결정, spec_volume_ml).
"""

import re
from decimal import Decimal
from typing import Any, Optional

UNIT = {"ml": "ml", "毫升": "ml", "l": "L", "리터": "L", "升": "L", "g": "g", "克": "g", "kg": "kg", "公斤": "kg", "千克": "kg"}
ML_PER = {"ml": 1, "L": 1000, "g": 1, "kg": 1000}
_AMT = r"(\d+(?:\.\d+)?)\s*(ml|毫升|kg|公斤|千克|l|리터|升|g|克)(?![a-z])"
# 개수 단위 — 긴 것부터 (개입 > 개, 소포 > 포)
WORDS = ["티백", "개입", "스틱", "소포", "세트", "박스", "상자", "개", "봉", "병", "캔", "포", "통", "팩", "컵", "갑", "알", "입", "盒", "瓶", "罐", "袋", "支", "听", "箱"]
_WORD = "(" + "|".join(WORDS) + ")"
PACK_WORDS = "(박스|상자|세트|봉|팩|통|갑|箱|盒)"
_X = r"\s*[×✕xX*＊]\s*"
_PAREN = re.compile(r"[(（]([^()（）]*)[)）]")
ADDON = re.compile(r"얼음설탕|설탕|증정|사은품")

FIELDS = ("unit_amount", "unit", "unit_count", "count_word", "pack_count", "total_count", "spec_note")


def _norm(s: str) -> str:
    s = re.sub(r"(?<=\d),(?=\d{3})", "", s)          # 1,020g → 1020g
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _per(total: Decimal, n: int) -> str:
    """총 무게 ÷ 개수 — 10 이상은 정수(과자 parse_spec 처럼 round), 작으면 소수 한 자리."""
    v = total / n
    return str(round(v)) if v >= 10 else str(v.quantize(Decimal("0.1")))


def _num(a: str) -> Decimal:
    return Decimal(a).quantize(Decimal("0.01"))


def _empty(note: Optional[str] = None, reason: Optional[str] = None) -> dict:
    d = {k: None for k in FIELDS}
    d["spec_note"] = note
    d["_reason"] = reason
    return d


def _part(head: str) -> Optional[dict]:
    """괄호를 뺀 규격 한 덩어리 → {amount, unit, count, word, pack}. 못 읽으면 None."""
    h = head.strip()
    # a) 3g×8티백 [×2박스]
    m = re.search(_AMT + _X + r"(\d+)\s*" + _WORD + "?" + r"(?:" + _X + r"(\d+)\s*" + PACK_WORDS + ")?", h, re.I)
    if m:
        one = re.search(_AMT + r"\s*1\s*" + _WORD, h[m.end():], re.I) if not m[4] else None
        if one:   # 50g×2 100g 1봉 — 단위 없는 ×N 은 속 구성, 파는 단위는 "100g 1봉" (과자 parse_spec 과 같게)
            return {"amount": one[1], "unit": one[2], "count": 1, "word": one[3], "pack": 1, "note": h[m.start():m.end()].strip()}
        return {"amount": m[1], "unit": m[2], "count": int(m[3]), "word": m[4], "pack": int(m[5]) if m[5] else 1}
    # a2) 20알 병×12 — 단위 앞에 용량이 없는 곱하기 (무게는 따로 찾는다)
    m = re.search(_WORD + _X + r"(\d+)", h)
    if m and not re.search(_AMT, h, re.I):
        return {"amount": None, "unit": None, "count": int(m[2]), "word": m[1], "pack": 1}
    # b) 375g 1통 · 1kg 1박스 · 550g 1박스 30봉
    m = re.search(_AMT + r"\s*1\s*" + _WORD, h, re.I)
    if m:
        return {"amount": m[1], "unit": m[2], "count": 1, "word": m[3], "pack": 1}
    # c) 1박스 547g · 36개입 417.6g 1박스 · 12개입 264g — 과자 parse_spec 처럼 "그 무게 1박스"
    m = re.search(r"(\d+)\s*" + _WORD + r"\s*(?:약\s*)?" + _AMT, h, re.I)
    if m:
        n, word = int(m[1]), m[2]
        if n == 1:
            return {"amount": m[3], "unit": m[4], "count": 1, "word": word, "pack": 1}
        if word == "개입":
            return {"amount": m[3], "unit": m[4], "count": 1, "word": "박스", "pack": 1, "note": f"{n}개입"}
        if n >= 20:   # 33봉 약 580g — 작은 봉 여러 개는 "1세트" (과자 parse_spec 규칙)
            return {"amount": m[3], "unit": m[4], "count": 1, "word": "세트", "pack": 1, "note": f"{n}{word}"}
        return {"amount": _per(Decimal(m[3]), n), "unit": m[4], "count": n, "word": word, "pack": 1, "approx": True}
    # d) 무게만 — 100g · 약 1kg · 2kg 약 160봉
    m = re.search(_AMT, h, re.I)
    if m:
        rest = h[m.end():]
        c = re.search(r"(\d+)\s*" + _WORD, rest)
        if c and int(c[1]) >= 20:   # 4斤 2kg 약 160봉 — 큰 봉 1박스
            return {"amount": m[1], "unit": m[2], "count": 1, "word": "박스", "pack": 1, "note": f"{c[1]}{c[2]}"}
        return {"amount": m[1], "unit": m[2], "count": 1, "word": None, "pack": 1}
    # e) 무게 없는 개수 — 10갑 · 1갑
    m = re.search(r"(\d+)\s*" + _WORD, h)
    if m:
        return {"amount": None, "unit": None, "count": int(m[1]), "word": m[2], "pack": 1}
    return None


def parse_option_spec(option2: Optional[str]) -> dict:
    """규격 글자 → 구조 칸 dict (FIELDS + spec_source='auto'). 못 읽으면 칸이 None 이고 _reason 에 사유."""
    if not option2 or not option2.strip():
        return {**_empty(reason="규격 없음"), "spec_source": "auto"}
    s = _norm(option2)
    notes = [p.strip() for p in _PAREN.findall(s) if p.strip()]
    head = _PAREN.sub(" ", s).strip()
    approx = bool(re.match(r"^(약|평균)\s*", head))
    flags: list[str] = []

    parts = [p for p in re.split(r"\s*\+\s*", head) if p.strip()] if "+" in head else [head]
    main_parts = [p for p in parts if not ADDON.search(p)]
    addons = [p for p in parts if ADDON.search(p)]
    parsed = [(_part(p), p) for p in main_parts]
    ok = [(d, p) for d, p in parsed if d]
    if not ok:
        return {**_empty(note=s, reason="규격을 못 읽음"), "spec_source": "auto"}
    if len(ok) < len(parsed):
        flags.append("일부 구성 못 읽음")

    # 무게 있는 첫 구성을 대표로 (섞인 구성은 개수만 더한다)
    rep = next((d for d, _ in ok if d["amount"]), ok[0][0])
    mixed = len(ok) > 1
    if mixed:
        # 무게 없는 "1박스" 같은 포장 단위 구성은 개수에서 뺀다 (과일칩 냉침차 1박스 + 티백 3g×8개 → 8, 예전 mart.unit_total 과 같게)
        countable = [d for d, _ in ok if d["amount"] or d["word"] not in ("박스", "상자", "세트", "통", "갑")]
        total = sum(d["count"] * d["pack"] for d in countable)
        flags.append("섞인 구성")
    else:
        total = rep["count"] * rep["pack"]

    amount, unit = rep["amount"], rep["unit"]
    # 무게만 적고 괄호에 "50g×3" 처럼 낱개 구성이 있으면 그쪽 (150g (50g×3) → 50g×3)
    if not mixed and rep["count"] == 1 and rep["word"] is None and amount:
        for n in notes:
            inner = _part(n)
            if inner and inner["amount"] and inner["count"] > 1 and "+" not in n:
                tot_in = Decimal(inner["amount"]) * ML_PER[UNIT[inner["unit"].lower()]] * inner["count"]
                if tot_in == Decimal(amount) * ML_PER[UNIT[unit.lower()]]:
                    rep = inner
                    amount, unit, total = inner["amount"], inner["unit"], inner["count"]
                    break
    # 무게 없는 개수 + 괄호 속 총 무게 (10갑 (약 460g, …)) → 개당 = 총 ÷ 개수
    if amount is None and not mixed:
        for n in notes:
            w = re.search(r"(?:약\s*)?" + _AMT, n, re.I)
            if w and not re.search(_AMT + r"\s*[×✕xX*＊]", n, re.I):
                cnt = rep["count"] * rep["pack"]
                if cnt >= 20:
                    amount, unit, rep = w[1], w[2], {**rep, "count": 1, "word": "세트", "pack": 1}
                    total = 1
                else:
                    amount, unit = _per(Decimal(w[1]), cnt), w[2]
                approx = True
                flags.append("괄호 속 총 무게로 개당 계산")
                break
    if amount is None:
        flags.append("무게·용량 없음")

    extra = [rep.get("note")] if rep.get("note") else []
    note = ", ".join([*extra, *notes, *(f"+{a.strip()}" for a in addons)]) or None
    if mixed:
        note = s if not note else f"{head} / {note}"
    if (approx or rep.get("approx")) and not (note or "").startswith("약"):
        note = f"약 · {note}" if note else "약"
    return {
        "unit_amount": _num(amount) if amount else None,
        "unit": UNIT[unit.lower()] if unit else None,
        "unit_count": rep["count"],
        "count_word": rep["word"],
        "pack_count": rep["pack"] if not mixed else 1,
        "total_count": total,
        "spec_note": note[:200] if note else None,
        "spec_source": "auto",
        "_reason": " · ".join(flags) or None,
    }


def spec_fields(option2: Optional[str]) -> dict:
    """DB 에 쓸 칸만 (_reason 뺌)."""
    return {k: v for k, v in parse_option_spec(option2).items() if not k.startswith("_")}


def _get(o: Any, k: str):
    return o.get(k) if isinstance(o, dict) else getattr(o, k, None)


def spec_volume_ml(o: Any) -> Optional[int]:
    """구조 칸으로 총 용량(ml, g 는 1g = 1ml) — unit_amount × total_count. 칸이 비었으면 None (예전 글자 해석으로)."""
    if o is None:
        return None
    amt, unit, total = _get(o, "unit_amount"), _get(o, "unit"), _get(o, "total_count")
    if amt is None or not unit or not total or unit not in ML_PER:
        return None
    cnt, pack = _get(o, "unit_count"), _get(o, "pack_count") or 1
    if cnt and int(total) != int(cnt) * int(pack):   # 섞인 구성(245ml×8병+100ml×4팩)은 개당 용량이 달라 곱할 수 없다 → 예전 해석
        return None
    v = int(Decimal(str(amt)) * ML_PER[unit] * int(total))
    return v if v > 0 else None


def spec_dict(o: Any) -> Optional[dict]:
    """마켓 등록 스크립트용 — cp_base.parse_spec 모양 {amt, unit, cnt, word} + total(한 옵션의 총 개수).
    구조 칸이 비었으면(용량 없음 포함) None → 예전 parse_spec 으로."""
    amt, unit = _get(o, "unit_amount"), _get(o, "unit")
    cnt, total = _get(o, "unit_count"), _get(o, "total_count")
    if amt is None or not unit or not cnt or not total:
        return None
    a = format(Decimal(str(amt)).normalize(), "f")
    pack = _get(o, "pack_count") or 1
    # mixed = 섞인 구성 (총 개수 ≠ 묶음 안 개수 × 묶음 수) — 마켓 아이템 이름은 규격 글자 그대로 쓴다
    return {"amt": a, "unit": unit, "cnt": int(cnt), "word": _get(o, "count_word") or "개", "total": int(total),
            "mixed": int(total) != int(cnt) * int(pack)}
