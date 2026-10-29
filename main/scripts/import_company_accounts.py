"""다른 서비스(FIN · MKT)의 계정을 AGC 회사 계정으로 한 번 옮긴다 (회사 정보 중앙화, 2026-10-29).

    <보내는 쪽 스크립트가 만든 JSON> | docker exec -i agc_app python -m scripts.import_company_accounts

stdin JSON:
    {"service": "fin", "items": [
        {"platform": "...", "login_id": "...", "password": "...",
         "url": null, "usages": ["정산"], "memo": null,
         "shared_with": ["fin"],          # 없으면 [service]
         "merge_into": 7}                 # 있으면 그 AGC 계정에 합침 (새로 만들지 않음)
    ]}

규칙
  · 평문 비밀번호는 stdin 으로만 받는다. 화면·로그에는 건수와 일치 여부만 찍는다.
  · 같은 계정 판단: merge_into 가 있으면 그 id, 없으면 살아 있는 행 중 platform·login_id 가 (대소문자 무시) 같은 것.
  · 합칠 때 AGC 비밀번호는 바꾸지 않는다(AGC 가 정본). shared_with 만 합치고, 비밀번호가 다르면 "다름" 으로 알린다.
  · 새로 만들 때 memo 앞에 "{SERVICE}에서 이전 (날짜)" 를 붙인다.
"""

import asyncio
import json
import sys
from datetime import date

from tortoise import Tortoise
from tortoise.transactions import in_transaction

from core.account_crypto import decrypt_secret, encrypt_secret
from core.internal_services import SERVICES, clean_shared_with
from database import TORTOISE_ORM
from models.company_account.company_account import CompanyAccount


async def run(payload: dict) -> None:
    service = (payload.get("service") or "").strip().lower()
    if service not in SERVICES:
        sys.exit(f"service 가 필요합니다 (가능: {', '.join(SERVICES)})")
    items = payload.get("items") or []
    created = merged = 0
    report: list[str] = []
    async with in_transaction():
        alive = await CompanyAccount.filter(deleted_at=None)
        for it in items:
            platform = (it.get("platform") or "").strip()
            login_id = (it.get("login_id") or "").strip()
            password = it.get("password")
            if not platform or not login_id or not password:
                report.append(f"  건너뜀: {platform or '?'} / {login_id or '?'} (빈 값)")
                continue
            shared = clean_shared_with(it.get("shared_with") if it.get("shared_with") is not None else [service])
            target = None
            if it.get("merge_into"):
                target = next((a for a in alive if a.id == int(it["merge_into"])), None)
                if not target:
                    sys.exit(f"merge_into={it['merge_into']} 계정을 찾지 못했습니다 — 전체 취소")
            else:
                target = next(
                    (a for a in alive
                     if a.platform.strip().lower() == platform.lower() and a.login_id.strip().lower() == login_id.lower()),
                    None,
                )
            if target:
                target.shared_with = clean_shared_with((target.shared_with or []) + shared)
                await target.save(update_fields=["shared_with", "updated_at"])
                same = decrypt_secret(target.password_enc) == password
                merged += 1
                report.append(f"  합침: id={target.id} {target.platform} · 공유 {target.shared_with} · 비밀번호 {'같음' if same else '다름(AGC 값 유지)'}")
            else:
                note = f"{service.upper()}에서 이전 ({date.today().isoformat()})"
                memo = (it.get("memo") or "").strip()
                a = await CompanyAccount.create(
                    platform=platform[:100],
                    login_id=login_id[:200],
                    password_enc=encrypt_secret(password),
                    url=(it.get("url") or None),
                    usages=[u for u in (it.get("usages") or []) if u][:10],
                    memo=f"{note}. {memo}" if memo else note,
                    shared_with=shared,
                )
                alive.append(a)
                created += 1
                report.append(f"  새로 만듦: id={a.id} {a.platform} · 공유 {a.shared_with}")
    print(f"[{service}] 받은 {len(items)} · 새로 {created} · 합침 {merged}")
    print("\n".join(report))


async def main() -> None:
    payload = json.loads(sys.stdin.read())
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        await run(payload)
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
