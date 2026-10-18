# core/account_crypto.py
# 회사 계정 비밀번호 암호화 — 다시 꺼내 봐야 하므로 해시가 아닌 복호화 가능한 암호화 (Fernet: AES-128-CBC + HMAC)
#
#   키: .env 의 ACCOUNT_SECRET_KEY (Fernet.generate_key() 값). 저장소에 커밋 금지.
#   ⚠️ 키를 잃어버리면 저장된 비밀번호를 하나도 복구할 수 없다 → .env 와 별도로 안전한 곳에 백업.
#   ⚠️ 평문·암호문 모두 로그에 남기지 않는다.

import os
from functools import lru_cache

from cryptography.fernet import Fernet


class AccountSecretKeyMissing(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.getenv("ACCOUNT_SECRET_KEY", "").strip()
    if not key:
        raise AccountSecretKeyMissing("ACCOUNT_SECRET_KEY 가 설정되지 않았습니다.")
    return Fernet(key.encode())


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
