from tortoise import fields
from tortoise.models import Model


class IssueReport(Model):
    """이슈 리포트 (2026-11-27 사용자 "이슈리포트라는 목록을 그냥 만드셈", Manager2 전달) — AGC 전체 문제 목록.
    kind 로 일반화: cost_diff(매입가 차이, 구매 기록 때 자동) · 나중에 measure_outlier · import_error · auth_blocked …
    status: new(새로) → ack(확인함) → resolved(해결). 같은 문제는 dedupe_key 로 한 줄."""
    id = fields.IntField(primary_key=True)
    kind = fields.CharField(max_length=30, index=True)
    status = fields.CharField(max_length=10, default="new", index=True)
    dedupe_key = fields.CharField(max_length=120, unique=True)
    title = fields.CharField(max_length=200)              # 대상 (제품 · 옵션 / 주문 코드)
    detail = fields.CharField(max_length=300)             # 내용 한 줄
    product_id = fields.IntField(null=True, index=True)
    option_id = fields.IntField(null=True, index=True)
    order_id = fields.IntField(null=True)
    order_code = fields.CharField(max_length=30, null=True)
    purchase_id = fields.IntField(null=True)
    data = fields.JSONField(null=True)
    memo = fields.TextField(null=True)
    reported_at = fields.DatetimeField(null=True)         # 점검 루틴이 보고한 때 (1회 보고)
    resolved_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "issue_report"
