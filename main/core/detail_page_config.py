# core/detail_page_config.py
# 상세페이지(디자인) 상수 — 상태 · 휴먼 체크 항목 · 확인 표시 규칙 · 공통 안내 기본값. 진실의 원천은 여기.
#   FE constants/designConst.js 와 문자열이 같아야 한다 (DETAIL_STATUS · REVIEW_CHECKS).

import re
from enum import Enum


class DetailStatus(str, Enum):
    """detail_page.status — 초안 → 검수 대기 → 승인 / 수정 필요."""
    DRAFT = "draft"          # 초안 — 만들기만 하고 아직 검수 요청 안 함
    REVIEW = "review"        # 검수 대기 — 사람이 확인할 차례
    APPROVED = "approved"    # 승인 — 사람이 휴먼 체크를 모두 하고 승인. 상품 등록은 이 상태만 받는다
    CHANGES = "changes"      # 수정 필요 — 검수자가 메모와 함께 돌려보냄


class ReviewAction(str, Enum):
    """detail_page_review.action — 검수 기록 (지우지 않는다)."""
    SUBMIT = "submit"        # 검수 요청
    APPROVE = "approve"      # 승인
    CHANGES = "changes"      # 수정 요청
    RESET = "reset"          # 승인 후 내용·공통 안내가 바뀌어 검수 대기로 되돌아감 (자동)


# 휴먼 체크 — 승인하려면 전부 체크해야 한다. FE REVIEW_CHECKS 와 키가 같아야 한다
REVIEW_CHECKS = (
    "reg_no",        # 수입식품등 인터넷 구매대행업 등록번호 확인
    "ingredients",   # 원재료를 실제 라벨과 대조
    "photo_promo",   # 사진 속 중국 현지 프로모션·문구 확인
    "claims",        # 효능·과장 표현 없음
    "draft_copy",    # 가안 문구 확정
)

# 확인 표시 — 본문에 [[...]] 로 쓴 부분. 미리보기에 노란 표시로 보이고, 하나라도 남아 있으면 승인할 수 없다
MARKER_RE = re.compile(r"\[\[(.+?)\]\]")

# 등록번호 — 비었거나 0 과 - 만 있으면(자리표시) 승인할 수 없다
REG_NO_PLACEHOLDER_RE = re.compile(r"^[0\-\s]*$")

# 공통 안내 (S6 · 등록번호) 기본값 — detail_page_common 행이 없을 때 이 값으로 만든다
DEFAULT_COMMON = {
    "reg_no": "",
    "seller": "이도식품",
    "notice_title": "해외구매대행 상품 안내",
    "notice": [
        {"title": "해외구매대행", "body": "중국 타오바오 공식 스토어에서 주문 후 구매해 보내드리는 상품이에요."},
        {"title": "배송 기간", "body": "결제 후 약 7~14일 (중국 웨이하이 해운 경유) [[가안]]"},
        {"title": "개인통관고유부호", "body": "통관을 위해 주문 시 꼭 입력해 주세요. 주문자와 수령인 이름이 같아야 해요."},
        {"title": "소비기한", "body": "현지 유통 제품이라 소비기한이 국내 제품보다 짧을 수 있어요. [[가안]]"},
        {"title": "파손 · 누수", "body": "받은 날 사진과 함께 문의해 주시면 확인 후 재발송 또는 환불해 드려요. [[가안]]"},
        {"title": "교환 · 반품", "body": "해외 주문 특성상 단순 변심 반품은 왕복 국제배송비가 발생해요. [[가안]]"},
    ],
}

# 마시는 법 아이콘 — FE DetailTemplate 의 HOW_ICONS 와 같아야 한다
HOW_ICONS = ("cold", "run", "bottle", "cup", "clock", "sun")

# 검수 기록을 상세 응답에 몇 건까지 줄지
REVIEW_HISTORY_SIZE = 10
