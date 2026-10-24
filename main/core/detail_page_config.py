# core/detail_page_config.py
# 상세페이지(디자인) 상수 — 상태 · 휴먼 체크 항목 · 확인 표시 규칙 · 공통 안내 기본값. 진실의 원천은 여기.
#   FE constants/designConst.js 와 문자열이 같아야 한다 (DETAIL_STATUS).

import re
from enum import Enum


class DetailStatus(str, Enum):
    """detail_page.status — 초안 → 검수 대기 → 승인 / 수정 필요."""
    DRAFT = "draft"          # 초안 — 만들기만 하고 아직 검수 요청 안 함
    REVIEW = "review"        # 검수 대기 — 사람이 확인할 차례
    APPROVED = "approved"    # 승인 — 사람이 미리보기를 보고 "확인" 을 누름. 상품 등록은 이 상태만 받는다
    CHANGES = "changes"      # 수정 필요 — 검수자가 메모와 함께 돌려보냄


class ReviewAction(str, Enum):
    """detail_page_review.action — 검수 기록 (지우지 않는다)."""
    SUBMIT = "submit"        # 검수 요청
    APPROVE = "approve"      # 승인
    CHANGES = "changes"      # 수정 요청
    RESET = "reset"          # 승인 후 내용·공통 안내가 바뀌어 검수 대기로 되돌아감 (자동)


# 휴먼 체크 — 사람이 미리보기를 보고 "확인" 한 번 누르면 끝 (2026-10-22 사용자 결정 — 아래 5개 체크리스트 폐지).
#   아래 키는 예전 기록(detail_page.review_checks · detail_page_review.checks)을 읽을 때의 참고용으로만 남긴다.
LEGACY_REVIEW_CHECKS = (
    "reg_no",        # 수입식품등 인터넷 구매대행업 등록번호 확인
    "ingredients",   # 원재료를 실제 라벨과 대조
    "photo_promo",   # 사진 속 중국 현지 프로모션·문구 확인
    "claims",        # 효능·과장 표현 없음
    "draft_copy",    # 가안 문구 확정
)

# 확인 표시 — 본문에 [[...]] 로 쓴 부분. 미리보기에 노란 표시로 보인다. 남아 있어도 확인(승인)은 되고 FE 가 경고만 한다
MARKER_RE = re.compile(r"\[\[(.+?)\]\]")

# 등록번호 — 비었거나 0 과 - 만 있으면(자리표시) 미입력으로 보고 FE 가 경고한다 (확인은 막지 않음)
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


# ── 상세 이미지 내보내기 ───────────────────────────────────────
# 승인된 상세페이지를 판매처별 폭의 이미지 조각으로 잘라 저장한다. FE utils/exportImages.js · constants/designConst.EXPORT_* 와 같아야 한다
# 형식 (2026-10-24 사용자 결정 — 품질 최대, 손해는 용량뿐): 네이버 PNG 무손실 · 쿠팡 JPG 품질 100 (쿠팡 상세 이미지는 JPG 만)
class ExportPlatform(str, Enum):
    """detail_page_export.platform — 상세 이미지를 올릴 판매처."""
    NAVER = "naver"          # 네이버 스마트스토어 — 폭 860px · PNG
    COUPANG = "coupang"      # 쿠팡 — 폭 780px (860px 그림을 줄임) · JPG


EXPORT_WIDTHS = {ExportPlatform.NAVER: 860, ExportPlatform.COUPANG: 780}
EXPORT_FORMATS = {ExportPlatform.NAVER: "png", ExportPlatform.COUPANG: "jpg"}   # 확장자 = 형식 (바이트로 확인)
EXPORT_MAX_FILE_BYTES = {                # 조각 1장 최대 크기 — 판매처 한도 (네이버 20MB · 쿠팡 10MB)
    ExportPlatform.NAVER: 20 * 1024 * 1024,
    ExportPlatform.COUPANG: 10 * 1024 * 1024,
}
EXPORT_MAX_HEIGHT = 3000                 # 조각 1장 최대 높이 (px) — 쿠팡 권장 3000 · 네이버 권장 5000 중 작은 값
EXPORT_MAX_TOTAL_HEIGHT = {ExportPlatform.COUPANG: 30000}   # 조각 높이 합계 한도 (쿠팡 상세 30,000px)
EXPORT_MAX_FILES = 20                    # 한 판매처 조각 최대 개수
EXPORT_MAX_TOTAL_BYTES = 45 * 1024 * 1024    # 한 번에 올리는 조각 합계 (nginx client_max_body_size 50m 안)
EXPORT_DIR = "detail"                    # UPLOAD_DIR 아래 폴더 — detail/{제품 코드}/v{버전}/{코드}_{판매처}_{순번}.{png|jpg}
