"""product_option 규격 구조 칸 채우기 (2026-11-22) — utils/option_spec.parse_option_spec.

    docker exec -w /app -e PYTHONPATH=/app agc_app python -m scripts.backfill_option_spec           # 연습 (DB 안 바꿈, 표만)
    docker exec -w /app -e PYTHONPATH=/app agc_app python -m scripts.backfill_option_spec --apply   # 실제로 채움

- spec_source='manual' 인 줄(사람이 고친 것)은 건드리지 않는다.
- 못 읽은 것 · 애매한 것 · 예전 해석(cp_base.parse_spec · mart.unit_total · 과자 parse_spec · utils/volume.parse_volume_ml)과
  다르게 나온 것을 /app/docs/option-spec-review.md (BE/docs 를 마운트했으면) 또는 /tmp/option-spec-review.md 에 표로 쓴다.
"""

import asyncio
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from tortoise import Tortoise

from database import TORTOISE_ORM
from utils.option_spec import FIELDS, parse_option_spec, spec_dict, spec_volume_ml
from utils.volume import parse_volume_ml

# ── 예전 해석 (비교용 사본 — 원본: scripts/market/cp_base.py · snack_cp.py · mart.py, 2026-11-22 시점) ──
_SPEC_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|L|l|g|G|kg|KG)\s*[×xX*]\s*(\d+)\s*([가-힣A-Za-z]+)?")
_UNIT = {"ml": "ml", "mL": "ml", "ML": "ml", "L": "L", "l": "L", "g": "g", "G": "g", "kg": "kg", "KG": "kg"}
_W_ONLY = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|L|l|g|G|kg|KG)(?![A-Za-z])")


def old_cp_spec(s):
    m = _SPEC_RE.search(s or "")
    if not m:
        w = _W_ONLY.search(s or "")
        if not w:
            return None
        amt, unit = w.groups()
        if "." in amt:
            amt = amt.rstrip("0").rstrip(".")
        return {"amt": amt, "unit": _UNIT[unit], "cnt": 1, "word": "개"}
    amt, unit, cnt, word = m.groups()
    if "." in amt:
        amt = amt.rstrip("0").rstrip(".")
    return {"amt": amt, "unit": _UNIT[unit], "cnt": int(cnt), "word": word or "개"}


def old_unit_total(option2, total):
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


_SW = r"(봉|갑|캔|박스|통|병|개|세트)"


def _mk(a, u, c, w):
    u = {"G": "g", "KG": "kg"}.get(u, u)
    if "." in a:
        a = a.rstrip("0").rstrip(".")
    return {"amt": a, "unit": u, "cnt": int(c), "word": w}


def old_snack_spec(s):
    full = s or ""
    s0 = full.split("(")[0].strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg)\s*[×xX*]\s*(\d+)\s*" + _SW, s0)
    if m: return _mk(m[1], m[2], m[3], m[4])
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g|kg)\s*1\s*" + _SW, s0)
    if m: return _mk(m[1], m[2], 1, m[3])
    m = re.search(r"1\s*" + _SW + r"\s*(\d+(?:\.\d+)?)\s*(g|kg)", s0)
    if m: return _mk(m[2], m[3], 1, m[1])
    m = re.search(r"(\d+)\s*개입\s*(\d+(?:\.\d+)?)\s*(g|kg)", s0)
    if m: return _mk(m[2], m[3], 1, "박스")
    m = re.search(r"병\s*[×x]\s*(\d+)", s0); g = re.search(r"약\s*(\d+)\s*g", full)
    if m and g: return _mk(str(round(int(g[1]) / int(m[1]))), "g", m[1], "병")
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg", s0)
    if m and "斤" in s0: return _mk(m[1], "kg", 1, "박스")
    m = re.search(r"(\d+)\s*" + _SW + r"\s*\(?\s*약?\s*(\d+(?:\.\d+)?)\s*(g|kg)", full)
    if m:
        n = int(m[1]); tot = float(m[3])
        if n >= 20: return _mk(m[3], m[4], 1, "세트")
        return _mk(str(round(tot / n)), m[4], n, m[2])
    return None


def fmt_spec(d, total=None):
    if not d:
        return "—"
    t = total if total is not None else d.get("total", d["cnt"])
    return f"{d['amt']}{d['unit']}×{d['cnt']}{d['word']} 총{t}"


def fmt_new(r):
    if r["unit_amount"] is None and r["unit_count"] is None:
        return "—"
    amt = f"{format(r['unit_amount'].normalize(), 'f')}{r['unit']}" if r["unit_amount"] is not None else "(무게없음)"
    pk = f"×{r['pack_count']}묶음" if (r["pack_count"] or 1) > 1 else ""
    return f"{amt}×{r['unit_count']}{r['count_word'] or ''}{pk} 총{r['total_count']}"


def cell(s):
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


async def main(argv):
    apply = "--apply" in argv
    await Tortoise.init(config=TORTOISE_ORM)
    conn = Tortoise.get_connection("default")
    cols = {r["column_name"] for r in await conn.execute_query_dict(
        "select column_name from information_schema.columns where table_name='product_option'")}
    has_cols = "spec_source" in cols
    sel = ", o.spec_source" if has_cols else ", null spec_source"
    rows = await conn.execute_query_dict(f"""select o.id, o.product_id, o.option1, o.option2{sel},
        p.category from product_option o join product p on p.id=o.product_id
        where o.deleted_at is null order by o.product_id, o.id""")
    fail, vague, diff, done, skipped = [], [], [], 0, 0
    for r in rows:
        if r["spec_source"] == "manual":
            skipped += 1
            continue
        res = parse_option_spec(r["option2"])
        new_s = spec_dict(res)
        reason = res.get("_reason")
        if res["unit_count"] is None:
            fail.append((r, reason or "못 읽음"))
        elif reason:
            vague.append((r, res, reason))
        # 예전 해석과 비교 — 마켓 스크립트(parse_spec) · 과자 parse_spec(기타 분류) · 배송비 용량
        old = old_cp_spec(r["option2"])
        old_total = old["cnt"] if old else None
        why = []
        if old and new_s:
            if (old["amt"], old["unit"]) != (new_s["amt"], new_s["unit"]):
                why.append("개당 용량")
            if old_total != new_s["total"]:
                why.append("총 개수")
        elif bool(old) != bool(new_s):
            why.append("한쪽만 읽음")
        snack = old_snack_spec(r["option2"]) if r["category"] == "other" else None
        if r["category"] == "other" and new_s and snack and ((snack["amt"], snack["unit"], snack["cnt"]) != (new_s["amt"], new_s["unit"], new_s["cnt"])):
            why.append("과자 해석과 다름")
        ov, nv = parse_volume_ml(r["option1"], r["option2"]), spec_volume_ml(res)
        if nv is not None and ov != nv:
            why.append("배송비 용량")
        if why:
            diff.append((r, fmt_spec(old, old_total), fmt_spec(snack) if snack else "", ov, fmt_new(res), nv, ", ".join(why)))
        if res["unit_count"] is not None:
            done += 1
        if apply and has_cols:
            vals = [res[k] for k in FIELDS]
            await conn.execute_query(
                "update product_option set unit_amount=$1, unit=$2, unit_count=$3, count_word=$4, pack_count=coalesce($5, 1), "
                "total_count=$6, spec_note=$7, spec_source='auto' where id=$8 and coalesce(spec_source, '') <> 'manual'", [*vals, r["id"]])

    kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    out = [f"# 옵션 규격(option2) 구조화 검토 목록", "",
           f"`scripts/backfill_option_spec.py` 실행 결과 ({kst} KST). 해석기 = `utils/option_spec.parse_option_spec`.", "",
           f"- 대상 옵션(살아 있는 것): {len(rows)}개 · 사람이 고친 것(manual, 건너뜀): {skipped}개",
           f"- 채움: {done}개 · 못 읽음: {len(fail)}개 · 애매함(읽었지만 확인 권장): {len(vague)}개 · 예전 해석과 다름: {len(diff)}개", "",
           "고치는 법: 옵션 PATCH `/price-surveys/{survey_id}/options/{option_id}` 에 칸(unit_amount · unit · unit_count · count_word · pack_count · total_count · spec_note)을 보내면 spec_source='manual', spec_checked=true 로 저장되고 다음 자동 해석에서 건너뛴다.", "",
           "## 1. 못 읽은 것", "", "| product_id | option_id | option1 | option2 | 사유 |", "|---|---|---|---|---|"]
    out += [f"| {r['product_id']} | {r['id']} | {cell(r['option1'])} | {cell(r['option2'])} | {cell(why)} |" for r, why in fail] or ["| — | | | | 없음 |"]
    out += ["", "## 2. 애매한 것 (읽었지만 사람이 한 번 보면 좋은 것)", "",
            "| product_id | option_id | option1 | option2 | 해석 결과 | 사유 |", "|---|---|---|---|---|---|"]
    out += [f"| {r['product_id']} | {r['id']} | {cell(r['option1'])} | {cell(r['option2'])} | {cell(fmt_new(res))} | {cell(why)} |" for r, res, why in vague]
    out += ["", "## 3. 예전 해석과 다르게 나온 것", "",
            "예전 = 마켓 스크립트 `parse_spec` · 과자 `parse_spec`(분류 other 만) · 배송비 `parse_volume_ml`(ml, option1+option2).",
            "새 해석이 맞으면 그대로 두고, 예전이 맞으면 옵션 PATCH 로 고친다.", "",
            "| product_id | option_id | option1 | option2 | 예전 parse_spec | 예전 과자 | 예전 용량ml | 새 해석 | 새 용량ml | 다른 곳 |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    out += [f"| {r['product_id']} | {r['id']} | {cell(r['option1'])} | {cell(r['option2'])} | {cell(o)} | {cell(sn)} | {cell(ov)} | {cell(n)} | {cell(nv)} | {cell(w)} |"
            for r, o, sn, ov, n, nv, w in diff]
    text = "\n".join(out) + "\n"
    path = "/app/docs/option-spec-review.md" if os.path.isdir("/app/docs") else "/tmp/option-spec-review.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"{'적용' if apply and has_cols else '연습'}: 대상 {len(rows)} · 채움 {done} · 못 읽음 {len(fail)} · 애매 {len(vague)} · 예전과 다름 {len(diff)} · manual {skipped} → {path}")
    if apply and not has_cols:
        print("! 칸이 아직 없습니다 — 마이그레이션(aerich upgrade) 먼저")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
