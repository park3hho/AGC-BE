# core/session.py
# Starlette SessionMiddleware + "로그인 유지" 구분
#
#   remember=True  → 쿠키에 Max-Age (기본 7일). 로그인이 필요한 요청마다 세션을 다시 써서 7일로 연장 (auth_deps).
#   remember=False → Max-Age 를 빼서 브라우저 세션 쿠키로 — 브라우저를 닫으면 사라진다.
#   서버 쪽 서명 유효기간(max_age)은 둘 다 같다 — 닫지 않은 브라우저도 7일 동안 요청이 없으면 만료.
#
# Starlette 는 max_age 를 미들웨어 단위로만 받으므로, 세션 값(REMEMBER_KEY)을 보고 Set-Cookie 만 고친다.

import re

from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware as StarletteSessionMiddleware
from starlette.types import Message, Receive, Scope, Send

REMEMBER_KEY = "remember"

_MAX_AGE_RE = re.compile(r"Max-Age=\d+; ", re.IGNORECASE)


class SessionMiddleware(StarletteSessionMiddleware):
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await super().__call__(scope, receive, send)
            return

        prefix = f"{self.session_cookie}="

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start" and not scope.get("session", {}).get(REMEMBER_KEY):
                headers = MutableHeaders(scope=message)
                cookies = headers.getlist("set-cookie")
                if any(c.startswith(prefix) for c in cookies):
                    del headers["set-cookie"]
                    for c in cookies:
                        headers.append("set-cookie", _MAX_AGE_RE.sub("", c) if c.startswith(prefix) else c)
            await send(message)

        await super().__call__(scope, receive, send_wrapper)
