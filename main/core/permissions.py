# core/permissions.py
# Role · Feature 정의 — FE src/constants/permissions.js 와 문자열이 같아야 한다 (DESIGN.md §5)

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"      # 관리자
    MEMBER = "member"    # 직원


class Feature(StrEnum):
    RESEARCH = "research"            # 제품·가격 조사 입력
    ACCOUNT_VIEW = "account_view"    # 회사 계정 보기 (비밀번호 열람 포함, 열람 기록 남음)
    ACCOUNT_EDIT = "account_edit"    # 회사 계정 추가·수정·삭제
    USER_MANAGE = "user_manage"      # 사용자 관리
    DETAIL_REVIEW = "detail_review"  # 상세페이지 휴먼 체크 — 승인 · 수정 요청 · 공통 안내(등록번호). API 키로는 못 씀


ROLE_FEATURES: dict[Role, frozenset[Feature]] = {
    Role.ADMIN: frozenset(Feature),
    Role.MEMBER: frozenset({Feature.RESEARCH, Feature.ACCOUNT_VIEW, Feature.DETAIL_REVIEW}),
}


def has_feature(role: str, feature: Feature) -> bool:
    try:
        return feature in ROLE_FEATURES[Role(role)]
    except ValueError:      # DB 에 모르는 role 이 들어있으면 권한 없음
        return False
