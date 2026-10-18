"""User → 응답 dict. password_hash · session_version 은 절대 넣지 않는다."""


def auth_user_dict(u) -> dict:
    return {"id": u.id, "username": u.username, "name": u.name, "role": u.role}


def user_dict(u) -> dict:
    return {
        **auth_user_dict(u),
        "active": u.active,
        "created_at": u.created_at.isoformat(),
        "updated_at": u.updated_at.isoformat(),
    }
