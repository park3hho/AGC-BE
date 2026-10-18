"""최초 관리자 계정 만들기 (1회성).

    docker compose exec app python -m scripts.create_admin

아이디·이름·비밀번호는 실행할 때 입력받는다 — 비밀번호를 명령줄 인자·파일·저장소에 남기지 않는다.
같은 아이디가 이미 있으면 아무것도 바꾸지 않고 끝낸다 (비밀번호 재설정은 관리자 화면의 PATCH /users/{id}).
"""

import asyncio
import getpass
import sys

from pydantic import ValidationError
from tortoise import Tortoise

from core.permissions import Role
from database import TORTOISE_ORM
from models.user.user import User
from schemas.user import UserCreate
from services.user.password import hash_password


def ask() -> UserCreate:
    username = input("관리자 아이디: ")
    name = input("이름: ")
    password = getpass.getpass("비밀번호 (8자 이상, 화면에 안 보임): ")
    if password != getpass.getpass("비밀번호 확인: "):
        sys.exit("비밀번호가 서로 다릅니다.")
    try:
        return UserCreate(username=username, name=name, password=password, role=Role.ADMIN)
    except ValidationError as e:
        sys.exit("입력 오류: " + "; ".join(err["msg"] for err in e.errors()))


async def main() -> None:
    body = ask()
    await Tortoise.init(config=TORTOISE_ORM)
    try:
        if await User.exists(username=body.username):
            sys.exit(f"이미 있는 아이디입니다: {body.username}")
        u = await User.create(
            username=body.username,
            name=body.name,
            password_hash=hash_password(body.password),
            role=Role.ADMIN.value,
        )
        print(f"관리자 생성 완료: id={u.id} username={u.username}")
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
