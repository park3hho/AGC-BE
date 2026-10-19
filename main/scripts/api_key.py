"""자동화용 API 키 관리 (리서처 skill 등). BE PC 에서만 실행한다 — API 로는 발급할 수 없다.

    docker compose exec app python -m scripts.api_key create --username researcher --name "리서처 skill"
    docker compose exec app python -m scripts.api_key list
    docker compose exec app python -m scripts.api_key revoke --id 3

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
from models.user.user import ApiKey, User
from services.user.password import hash_password

KEY_PREFIX = "agc_"


async def create(username: str, name: str) -> None:
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
    key = await ApiKey.create(user=user, name=name, key_prefix=raw[:12], key_hash=hash_api_key(raw))
    print(f"API 키 발급: id={key.id} user={user.username} name={name}")
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
        print(f"id={k.id} [{state}] {k.key_prefix}… user={k.user.username} name={k.name} 마지막 사용={used}")


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
    sub.add_parser("list", help="키 목록")
    r = sub.add_parser("revoke", help="키 폐기")
    r.add_argument("--id", type=int, required=True)
    args = parser.parse_args()

    await Tortoise.init(config=TORTOISE_ORM)
    try:
        if args.cmd == "create":
            await create(args.username, args.name)
        elif args.cmd == "list":
            await list_keys()
        else:
            await revoke(args.id)
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
