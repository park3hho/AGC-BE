"""코드 발급 — {PREFIX}-{YYMMDD}-{XXXX}. XXXX 는 그날의 순번 16진수 대문자 4자리 (0001 ~ FFFF).

    PR-261018-0001   제품 (날짜 = 제품 추가일, KST)
    RS-261018-000A   가격 조사 (날짜 = 조사일)

순번은 같은 날짜·접두사 중 가장 큰 코드 + 1. 대문자 고정 길이라 문자열 정렬 = 숫자 정렬이다.
동시에 두 건이 같은 번호를 잡으면 DB unique 가 막는다 → 호출측이 IntegrityError 때 다시 발급한다.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException

PRODUCT_CODE_PREFIX = "PR"
SURVEY_CODE_PREFIX = "RS"
CODE_MAX_SEQ = 0xFFFF
CODE_ISSUE_RETRIES = 5        # 동시 발급 충돌 시 재시도 횟수

KST = ZoneInfo("Asia/Seoul")


def today_kst() -> date:
    return datetime.now(KST).date()


async def next_code(model, prefix: str, day: date) -> str:
    head = f"{prefix}-{day.strftime('%y%m%d')}-"
    last = await model.filter(code__startswith=head).order_by("-code").first().values_list("code", flat=True)
    seq = int(last[len(head):], 16) + 1 if last else 1
    if seq > CODE_MAX_SEQ:
        raise HTTPException(status_code=409, detail=f"{head} 코드를 하루 최대치(FFFF)까지 다 썼습니다.")
    return f"{head}{seq:04X}"
