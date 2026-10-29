from typing import Optional
from urllib.parse import urlsplit

from core.config import UPLOAD_URL_PREFIX


def clean_str(v: Optional[str]) -> Optional[str]:
    """앞뒤 공백 제거. 빈 문자열은 None 으로."""
    if v is None:
        return None
    v = v.strip()
    return v or None


def check_url(v: Optional[str]) -> Optional[str]:
    """http(s):// 주소만 허용. None 은 그대로."""
    v = clean_str(v)
    if v is not None and not v.lower().startswith(("http://", "https://")):
        raise ValueError("주소는 http:// 또는 https:// 로 시작해야 합니다.")
    return v


def check_photo_url(v: Optional[str]) -> Optional[str]:
    """사진 주소 — 외부 http(s) 주소 또는 이 서버에 올린 사진(/files/...)."""
    v = clean_str(v)
    if v is None:
        return None
    if v.startswith(f"{UPLOAD_URL_PREFIX}/"):
        if ".." in v:
            raise ValueError("사진 주소가 올바르지 않습니다.")
        return v
    return check_url(v)

# ── 여러 스키마가 같이 쓰는 검사 (옛 schemas/company_account.py 에서 옮김, 2026-10-30) ──
URL_MAX_LEN = 500


def _required_text(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("값을 입력해주세요.")
    return v


def _clean_url(v: Optional[str]) -> Optional[str]:
    """빈 값 → None. 'www.foodsafetykorea.go.kr' 처럼 주소만 쓰면 https:// 를 붙인다. http/https 만 허용."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if "://" not in v:
        v = "https://" + v
    parts = urlsplit(v)
    if parts.scheme not in ("http", "https") or not parts.netloc or " " in v:
        raise ValueError("홈페이지 주소를 확인해주세요 (예: https://www.foodsafetykorea.go.kr).")
    if len(v) > URL_MAX_LEN:
        raise ValueError(f"홈페이지 주소는 {URL_MAX_LEN}자 이하로 입력해주세요.")
    return v
