from tortoise import fields

from models.base import BaseModel


class AgentAlert(BaseModel):
    """AI(루틴)·서버가 사용자에게 알린 것 — 같은 key 는 한 번만 알린다 (2026-11-19, 루틴 메모의 '보고함 · 재보고 금지' 대신).

    key 규칙: {kind}:{대상}[:{단계·숫자}] — 예 deadline_d3:OR-261116-000A, bundle_partial:PRE_LP000000001D:1/2.
    resolved 면 같은 key 가 다시 오면 새 알림으로 연다."""

    key = fields.CharField(max_length=200, unique=True)
    kind = fields.CharField(max_length=30, index=True)              # core/ops_config.ALERT_KIND
    level = fields.CharField(max_length=10, default="info")         # info 알림 · action 사용자 할 일 · blocked 막힘
    title = fields.CharField(max_length=200)
    body = fields.TextField(null=True)
    order_codes = fields.JSONField(default=list)                    # ["OR-…"]
    target = fields.CharField(max_length=60, null=True)             # PRE_LP… · purchase:65 · B/L 번호 등
    source = fields.CharField(max_length=60, null=True)             # routine:{id} · auto:{이름} · user
    count = fields.IntField(default=1)                              # 같은 key 가 몇 번 왔는지 (재보고 막은 횟수 + 1)
    first_at = fields.DatetimeField(auto_now_add=True)
    last_at = fields.DatetimeField(null=True)
    resolved_at = fields.DatetimeField(null=True)
    resolved_by = fields.CharField(max_length=60, null=True)

    class Meta:
        table = "agent_alert"
