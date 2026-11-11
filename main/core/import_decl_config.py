"""수입식품 구매대행 수입신고 설정 (2026-11-11). playbook: AGC-FE src/playbooks/import-declaration.md"""

DECL_KIND = {"pre": "사전신고 (입항 전)", "main": "본신고 (입항 후)"}

# draft 작성 중 · sent 전송완료(기관발송) · accepted 접수 · approved 수리 · fix 보완요청 · rejected 반려 · missed 통관 뒤라 못 냄
DECL_STATUS = {
    "draft": "작성 중",
    "sent": "전송완료",
    "accepted": "접수",
    "approved": "수리",
    "fix": "보완요청",
    "rejected": "반려",
    "missed": "못 냄 (통관 뒤)",
}
DECL_OK = ("sent", "accepted", "approved")      # 낸 것으로 보는 상태

DECL_TRACKED = ("decl_no", "receipt_no", "kind", "status", "agency_code", "bl_no", "vessel", "arrival_date",
                "warehouse_code", "consignee", "items", "seller_site", "shipper_site", "sent_at", "accepted_at",
                "approved_at", "result", "memo")

DECL_DEFAULTS = {"agency_code": "1471290", "warehouse_code": "02002004"}   # 인천항 해상 · 인천세관 지정장치장
