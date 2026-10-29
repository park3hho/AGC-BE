"""자동화용 API 키 관리 (리서처 skill 등). BE PC 에서만 실행한다 — API 로는 발급할 수 없다.

    docker compose exec app python -m scripts.api_key create --username researcher --name "리서처 skill"
    docker compose exec app python -m scripts.api_key list
    docker compose exec app python -m scripts.api_key revoke --id 3
    docker compose exec app python -m scripts.api_key create --service fin     # 서비스 키 (사용자 svc-fin)

서비스 키 (--service fin|mkt|shop):
  · /internal/company 전용 (core/internal_services.py). 일반 API 는 403.
  · 사용자 svc-{서비스} 를 만든다 — 열람 기록에 이 사용자로 남는다.
  · --out 파일을 주면 원문을 화면에 찍지 않고 그 파일에만 쓴다 (각 서비스 .env 로 옮기는 용도).

create:
  · 사용자가 없으면 직원(member) 계정을 새로 만든다. 비밀번호는 아무도 모르는 임의값 → 화면 로그인은 안 되고 키로만 쓴다.
  · 키 원문은 이때 **한 번만** 출력된다. DB 에는 sha256 해시만 남는다 → 잃어버리면 폐기하고 새로 발급.
  · 키로는 로그인 · research 권한 API 만 쓸 수 있다 (core/auth_deps.py). 사용자를 비활성화하면 키도 바로 막힌다.
"""

import argparse
import asyncio
import secrets
import sys

from tortoise import Tortoise

from core.auth_deps import hash_api_key
from core.permissions import Role
from database import TORTOISE_ORM
from core.internal_services import SERVICES
from models.user.user import ApiKey, User
from services.user.password import hash_password

KEY_PREFIX = "agc_"


async def create(username: str, name: str, service: str | None = None, out: str | None = None) -> None:
    if service:
        service = service.strip().lower()
        if service not in SERVICES:
            sys.exit(f"모르는 서비스입니다: {service} (가능: {', '.join(SERVICES)})")
        username, name = f"svc-{service}", f"서비스 · {SERVICES[service]}"
    username = username.strip().lower()
    user = await User.get_or_none(username=username)
    if not user:
        user = await User.create(
            username=username,
            name=name,
            password_hash=hash_password(secrets.token_urlsafe(32)[:60]),
            role=Role.MEMBER.value,
        )
        print(f"직원 계정 생성: id={user.id} username={user.username} (화면 로그인 불가, 키 전용)")
    elif not user.active:
        sys.exit(f"사용 중지된 계정입니다: {username} — 관리자 화면에서 다시 켠 뒤 발급하세요.")

    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    key = await ApiKey.create(
        user=user, name=name, key_prefix=raw[:12], key_hash=hash_api_key(raw), service=service or None
    )
    print(f"API 키 발급: id={key.id} user={user.username} name={name} service={service or '-'}")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(raw)
        print(f"원문은 {out} 에만 썼습니다. 옮긴 뒤 파일을 지우세요.")
        return
    print()
    print(raw)
    print()
    print("↑ 이 키는 다시 볼 수 없습니다. 사용할 PC 의 환경변수 AGC_API_KEY 에 넣으세요. 저장소·채팅에 붙여 넣지 마세요.")


async def list_keys() -> None:
    rows = await ApiKey.all().select_related("user").order_by("id")
    if not rows:
        print("발급된 키가 없습니다.")
        return
    for k in rows:
        state = "사용" if k.active else "폐기"
        used = k.last_used_at.isoformat() if k.last_used_at else "-"
        svc = f" service={k.service}" if k.service else ""
        print(f"id={k.id} [{state}] {k.key_prefix}… user={k.user.username} name={k.name}{svc} 마지막 사용={used}")


async def revoke(key_id: int) -> None:
    key = await ApiKey.get_or_none(id=key_id)
    if not key:
        sys.exit(f"없는 키입니다: id={key_id}")
    key.active = False
    await key.save(update_fields=["active", "updated_at"])
    print(f"폐기 완료: id={key.id} {key.key_prefix}…")


async def main() -> None:
    parser = argparse.ArgumentParser(description="API 키 관리")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="키 발급")
    c.add_argument("--username", default="researcher")
    c.add_argument("--name", default="리서처 skill")
    c.add_argument("--service", default=None, help="서비스 키: fin | mkt | shop")
    c.add_argument("--out", default=None, help="원문을 화면 대신 이 파일에 씀")
    sub.add_parser("list", help="키 목록")
    r = sub.add_parser("revoke", help="키 폐기")
    r.add_argument("--id", type=int, required=True)
    args = parser.parse_args()

    await Tortoise.init(config=TORTOISE_ORM)
    try:
        if args.cmd == "create":
            await create(args.username, args.name, args.service, args.out)
        elif args.cmd == "list":
            await list_keys()
        else:
            await revoke(args.id)
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
