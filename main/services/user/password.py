"""bcrypt 해시 — 로그인 비밀번호 전용 (회사 계정 비밀번호는 core/account_crypto.py)."""

import bcrypt

# 없는 아이디로 로그인할 때도 같은 시간만큼 검사해서, 응답 시간으로 아이디 존재 여부를 알 수 없게 한다
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str | None) -> bool:
    raw = plain.encode("utf-8")
    if len(raw) > 72:       # bcrypt 5 는 72바이트 초과 시 ValueError — 이런 비밀번호로는 만들 수 없으므로 실패
        bcrypt.checkpw(b"x", _DUMMY_HASH)
        return False
    if not hashed:
        bcrypt.checkpw(raw, _DUMMY_HASH)
        return False
    return bcrypt.checkpw(raw, hashed.encode("ascii"))
