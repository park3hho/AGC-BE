"""마켓 주문 조회 클라이언트 (읽기 전용) — 네이버 커머스API · 쿠팡 OpenAPI.
키는 API 키 저장소(ApiCredential)에서 꺼낸다. 키·토큰·응답 본문은 로그에 남기지 않는다."""

import asyncio
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import bcrypt

from services.company_account.api_credential_service import credential_values

KST = timezone(timedelta(hours=9))
TIMEOUT = 30


class MarketApiError(RuntimeError):
    """마켓 호출 실패 — 메시지에는 상태 코드와 마켓이 준 짧은 사유만 (키·개인정보 없음)."""


def _http(method: str, url: str, headers: dict, body: bytes | None = None) -> dict:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            info = json.loads(e.read() or b"{}")
            reason = info.get("message") or info.get("code") or ""
        except Exception:
            reason = ""
        raise MarketApiError(f"HTTP {e.code} {str(reason)[:200]}") from None
    except urllib.error.URLError as e:
        raise MarketApiError(f"연결 실패 {type(e.reason).__name__}") from None


async def http(method, url, headers, body=None) -> dict:
    return await asyncio.to_thread(_http, method, url, headers, body)


# ---------------------------------------------------------------- 네이버
NAVER_BASE = "https://api.commerce.naver.com/external"
NAVER_SERVICE = "네이버 커머스API"
_naver_token: dict = {"value": None, "exp": 0.0}


async def _naver_auth() -> str:
    if _naver_token["value"] and time.time() < _naver_token["exp"] - 60:
        return _naver_token["value"]
    public, secrets = await credential_values(NAVER_SERVICE)
    cid, secret = public["애플리케이션 ID"], secrets["애플리케이션 시크릿"]
    ts = str(int(time.time() * 1000))
    sign = base64.b64encode(bcrypt.hashpw(f"{cid}_{ts}".encode(), secret.encode())).decode()
    body = urllib.parse.urlencode({
        "client_id": cid, "timestamp": ts, "client_secret_sign": sign, "grant_type": "client_credentials", "type": "SELF",
    }).encode()
    data = await http("POST", f"{NAVER_BASE}/v1/oauth2/token", {"Content-Type": "application/x-www-form-urlencoded"}, body)
    _naver_token.update(value=data["access_token"], exp=time.time() + int(data.get("expires_in", 3600)))
    return _naver_token["value"]


async def naver_changed_product_order_ids(since: datetime, until: datetime) -> list[str]:
    """since~until 사이에 상태가 바뀐 상품주문번호 (네이버는 한 번에 24시간까지 → 하루씩 나눠 부른다)."""
    token = await _naver_auth()
    ids: list[str] = []
    start = since
    # 끝에 1초도 안 되는 자투리 구간이 남으면 네이버가 '조회 날짜가 유효하지 않습니다'(400)로 거절한다 → 건너뜀 (다음 수집이 10분 겹쳐 받음)
    while until - start > timedelta(seconds=1):
        end = min(start + timedelta(hours=24), until)
        params = {"lastChangedFrom": start.astimezone(KST).isoformat(timespec="milliseconds"),
                  "lastChangedTo": end.astimezone(KST).isoformat(timespec="milliseconds")}
        while True:
            url = f"{NAVER_BASE}/v1/pay-order/seller/product-orders/last-changed-statuses?" + urllib.parse.urlencode(params)
            data = (await http("GET", url, {"Authorization": f"Bearer {token}"})).get("data") or {}
            ids += [s["productOrderId"] for s in data.get("lastChangeStatuses") or []]
            more = data.get("more")
            if not more:
                break
            params["lastChangedFrom"], params["moreSequence"] = more["moreFrom"], more["moreSequence"]
        start = end
    return list(dict.fromkeys(ids))


async def naver_product_orders(ids: list[str]) -> list[dict]:
    """상품주문 상세 (한 번에 300개까지)."""
    token = await _naver_auth()
    out: list[dict] = []
    for i in range(0, len(ids), 300):
        body = json.dumps({"productOrderIds": ids[i:i + 300]}).encode()
        data = await http("POST", f"{NAVER_BASE}/v1/pay-order/seller/product-orders/query",
                          {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, body)
        out += data.get("data") or []
    return out


# ---------------------------------------------------------------- 쿠팡
COUPANG_BASE = "https://api-gateway.coupang.com"
COUPANG_SERVICE = "쿠팡 OpenAPI"
COUPANG_RECEIVE_STATUSES = ("ACCEPT", "INSTRUCT")      # 결제완료 · 상품준비중 — 접수 단계


async def _coupang_call(method: str, path: str, query: str = "", body: dict | None = None) -> dict:
    public, secrets = await credential_values(COUPANG_SERVICE)
    dt = datetime.now(timezone.utc).strftime("%y%m%dT%H%M%SZ")
    sig = hmac.new(secrets["Secret Key"].encode(), (dt + method + path + query).encode(), hashlib.sha256).hexdigest()
    auth = f"CEA algorithm=HmacSHA256, access-key={secrets['Access Key']}, signed-date={dt}, signature={sig}"
    url = f"{COUPANG_BASE}{path}" + (f"?{query}" if query else "")
    data = json.dumps(body).encode() if body is not None else None
    return await http(method, url, {"Authorization": auth, "Content-Type": "application/json;charset=UTF-8"}, data)


async def _coupang_get(path: str, query: str) -> dict:
    return await _coupang_call("GET", path, query)


async def coupang_vendor_id() -> str:
    public, _ = await credential_values(COUPANG_SERVICE)
    return public["업체코드 (vendorId)"]


async def coupang_ordersheets(since: datetime, until: datetime, statuses=COUPANG_RECEIVE_STATUSES) -> list[dict]:
    """발주서 목록 (일 단위 · 상태별). 쿠팡은 한 번에 31일까지 → 30일씩 나눈다."""
    vendor = await coupang_vendor_id()
    path = f"/v2/providers/openapi/apis/api/v5/vendors/{vendor}/ordersheets"
    out: list[dict] = []
    d_from, d_to = since.astimezone(KST).date(), until.astimezone(KST).date()
    for status in statuses:
        start = d_from
        while start <= d_to:
            end = min(start + timedelta(days=30), d_to)
            token = ""
            while True:
                q = {"createdAtFrom": f"{start.isoformat()}+09:00", "createdAtTo": f"{end.isoformat()}+09:00", "status": status, "maxPerPage": 50}
                if token:
                    q["nextToken"] = token
                data = await _coupang_get(path, urllib.parse.urlencode(q))
                if str(data.get("code")) not in ("200", "SUCCESS"):
                    raise MarketApiError(f"쿠팡 {data.get('code')} {str(data.get('message'))[:200]}")
                out += data.get("data") or []
                token = data.get("nextToken") or ""
                if not token:
                    break
            start = end + timedelta(days=1)
    return out


# ---------------------------------------------------------------- 발주확인 (쓰기) — 2026-10-25
async def coupang_acknowledge(shipment_box_ids: list[str]) -> dict:
    """쿠팡 상품준비중 처리 (결제완료 ACCEPT 에서만). 반환: {box_id: (성공, 메시지)} + raw."""
    vendor = await coupang_vendor_id()
    path = f"/v2/providers/openapi/apis/api/v4/vendors/{vendor}/ordersheets/acknowledgement"
    body = {"vendorId": vendor, "shipmentBoxIds": [int(x) for x in shipment_box_ids]}
    data = await _coupang_call("PUT", path, "", body)
    if str(data.get("code")) not in ("200", "SUCCESS"):
        raise MarketApiError(f"쿠팡 {data.get('code')} {str(data.get('message'))[:200]}")
    result = {}
    for r in (data.get("data") or {}).get("responseList") or []:
        result[str(r.get("shipmentBoxId"))] = (bool(r.get("succeed")), str(r.get("resultMessage") or r.get("resultCode") or ""))
    return {"result": result, "raw": data}


async def naver_confirm(product_order_ids: list[str]) -> dict:
    """네이버 발주 확인 (한 번에 30건까지). 반환: {productOrderId: (성공, 메시지)} + raw."""
    token = await _naver_auth()
    result, raws = {}, []
    for i in range(0, len(product_order_ids), 30):
        body = json.dumps({"productOrderIds": product_order_ids[i:i + 30]}).encode()
        data = await http("POST", f"{NAVER_BASE}/v1/pay-order/seller/product-orders/confirm",
                          {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, body)
        raws.append(data)
        d = data.get("data") or {}
        for s in d.get("successProductOrderInfos") or []:
            result[str(s.get("productOrderId"))] = (True, "")
        for f in d.get("failProductOrderInfos") or []:
            result[str(f.get("productOrderId"))] = (False, str(f.get("message") or f.get("code") or ""))
    return {"result": result, "raw": raws}
