"""옵션 이름에서 음료 총 용량(ml)을 읽는다 — 배송비 무게 계산용 (core/shipping_config.py).

    parse_volume_ml("코코넛밀크", "245ml×24팩")  → 5880
    parse_volume_ml("1L×6팩")                   → 6000
    parse_volume_ml("椰汁245ml*24盒")            → 5880
    parse_volume_ml("1.5L")                     → 1500   (개수가 없으면 1개)
    parse_volume_ml("오리지널", "205g×10팩")       → 2050   (g 는 ml 로 본다, 1g = 1ml)
    parse_volume_ml("1.25kg×6병")               → 7500
    parse_volume_ml("복숭아맛")                  → None   (용량을 못 읽음)

규칙: 첫 번째 "숫자 + ml/L/g/kg" 를 용량으로 보고 (g·kg 는 1g = 1ml 로 환산, 2026-10-24 사용자 결정), 그 뒤의 "×N" (또는 "N팩/N개/N盒" …) 를 개수로 본다.
"""

import re
from decimal import Decimal
from typing import Optional

# 숫자 + 단위. ml 을 l 보다, kg 를 g 보다 먼저 본다. 단위 뒤에 영문자가 붙으면(예: 5lb) 용량이 아니다.
# g·kg 는 무게지만 음료는 1g = 1ml 로 본다 (2026-10-24 사용자 결정).
_VOLUME = re.compile(
    r"(\d+(?:\.\d+)?)\s*(ml|毫升|kg|公斤|千克|l|리터|升|g|克)(?![a-z])", re.IGNORECASE
)
# ×N — 곱하기 기호 여러 가지 (× ✕ x X * ＊)
_TIMES = re.compile(r"^\s*[×✕xX*＊]\s*(\d+)")
# N팩 · N개 … (곱하기 기호 없이 개수만 적은 경우)
_COUNT_UNIT = re.compile(r"(\d+)\s*(팩|개|병|캔|입|박스|盒|瓶|罐|支|袋|听|箱)")

_ML_PER_UNIT = {
    "ml": 1, "毫升": 1, "l": 1000, "리터": 1000, "升": 1000,
    "g": 1, "克": 1, "kg": 1000, "公斤": 1000, "千克": 1000,
}


def parse_volume_ml(*texts: Optional[str]) -> Optional[int]:
    text = " ".join(t for t in texts if t)
    m = _VOLUME.search(text)
    if not m:
        return None
    per_unit = Decimal(m.group(1)) * _ML_PER_UNIT[m.group(2).lower()]

    rest = text[m.end():]
    count = 1
    times = _TIMES.match(rest)
    if times:
        count = int(times.group(1))
    else:
        unit = _COUNT_UNIT.search(rest)
        if unit:
            count = int(unit.group(1))

    total = int(per_unit * count)
    return total if total > 0 else None


def scale_pack(text: Optional[str], n: int) -> Optional[dict]:
    """옵션 이름의 개수를 N배로 — 묶음 판매 옵션 이름용.

        scale_pack("330ml×24캔", 2) → {"text": "330ml×48캔", "count": 48, "unit_text": "24캔"}
        scale_pack("125ml*36盒", 3) → {"text": "125ml*108盒", "count": 108}
        scale_pack("1.5L", 4)       → {"text": "1.5L×4", "count": 4}
        scale_pack("복숭아맛", 2)     → None   (용량을 못 읽음)
    """
    if not text:
        return None
    m = _VOLUME.search(text)
    if not m:
        return None
    rest = text[m.end():]
    times = _TIMES.match(rest)
    if times:
        count = int(times.group(1))
        s, e = m.end() + times.start(1), m.end() + times.end(1)
    else:
        unit = _COUNT_UNIT.search(rest)
        if not unit:
            return {"text": f"{text[:m.end()]}×{n}{text[m.end():]}", "count": n, "unit_text": text[m.start():m.end()]}
        count = int(unit.group(1))
        s, e = m.end() + unit.start(1), m.end() + unit.end(1)
    # unit_text = 원래 한 묶음을 나타내는 부분 ("24캔") — "24캔×2" 같은 설명에 쓴다
    return {"text": f"{text[:s]}{count * n}{text[e:]}", "count": count * n, "unit_text": text[s:].strip()}