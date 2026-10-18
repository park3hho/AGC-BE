from typing import Optional

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
