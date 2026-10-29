# core/internal_services.py
# 회사 정보 중앙화 (2026-10-29) — 회사 계정·API 키는 AGC DB 한 곳에만 두고,
# 같은 PC 의 다른 서비스(FIN · MKT · SHOP)는 /internal/company/... 로 조회한다.
#
#   · 행마다 shared_with = ["fin", "mkt"] 처럼 볼 수 있는 서비스를 적는다. 비어 있으면 AGC 사람만 본다.
#   · 서비스 키 = api_key.service 가 채워진 X-API-Key. scripts/api_key.py create --service fin 으로만 발급.
#   · 서비스 키는 /internal 전용 — 일반 API 에서는 403 (core/auth_deps.require_auth).
#   · /internal 은 nginx 에서 404 (밖에서 못 들어옴). 같은 Docker 네트워크(be_default)에서 http://agc_app:8000 으로만.
#   FE src/constants 의 공유 서비스 목록과 문자열이 같아야 한다.

SERVICES: dict[str, str] = {
    "fin": "FIN (회계)",
    "mkt": "MKT (마케팅)",
    "shop": "SHOP (자사몰)",
}


def clean_shared_with(v: list[str] | None) -> list[str]:
    """중복 제거 · 소문자 · 정해진 서비스만. 순서는 SERVICES 순서로 맞춘다."""
    if v is None:
        return []
    picked = {s.strip().lower() for s in v if s and s.strip()}
    unknown = picked - set(SERVICES)
    if unknown:
        raise ValueError(f"모르는 서비스입니다: {', '.join(sorted(unknown))} (가능: {', '.join(SERVICES)})")
    return [s for s in SERVICES if s in picked]
