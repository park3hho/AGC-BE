"""회사 정보 › 기본 정보 설정 — 앱 연결(link) 목록 · 서류 파일 제한. api-contract.md '회사 정보 › 기본 정보'"""

# 앱에서 기본 정보 값을 가져다 쓰는 곳. key 는 항목 하나에만 붙는다.
INFO_LINKS = [
    {"key": "biz_reg_no", "label": "사업자등록번호", "used_by": "상품 등록 (예정)"},
    {"key": "mail_order_no", "label": "통신판매업 신고번호", "used_by": "상품 등록 (예정)"},
    {"key": "food_agency_reg_no", "label": "수입식품등 인터넷구매대행업 영업등록번호", "used_by": "상세페이지 S6 등록번호"},
    {"key": "ecommerce_code", "label": "전자상거래업자부호", "used_by": "통관 (예정)"},
]
INFO_LINK_KEYS = {l["key"] for l in INFO_LINKS}
LINK_FOOD_AGENCY_REG_NO = "food_agency_reg_no"     # 상세페이지 공통 안내 reg_no 가 이 값을 쓴다

DETAILS_MAX = 20
INFO_FILES_MAX = 10                                 # 항목 하나에 붙일 수 있는 파일 수
INFO_FILE_MAX_BYTES = 20 * 1024 * 1024              # 20MB

# 파일 앞부분 바이트 → (확장자, content_type)
INFO_FILE_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
