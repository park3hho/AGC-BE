"""라우터 응답 포맷 헬퍼 — 모든 성공 응답은 `{"status": "success", ...data}`.

    return success(item=item_dict)
    return success(items=items, total=len(items))
    return success_only()          # DELETE 등 데이터 없는 성공
"""


def success(**data) -> dict:
    return {"status": "success", **data}


def success_only() -> dict:
    return {"status": "success"}
