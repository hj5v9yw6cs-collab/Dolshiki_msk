"""Вход в систему и текущий пользователь."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..casework import ROLES
from ..core.security import (
    hash_password,
    new_session_token,
    token_fingerprint,
    verify_password,
)
from ..db import get_session
from ..models import Session, User
from ..schemas import LoginRequest, PasswordChange
from .deps import Actor, current_actor, login_limiter, client_ip

router = APIRouter(prefix="/api/v1/auth", tags=["Доступ"])

SESSION_DAYS = 30


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "role_title": ROLES.get(user.role, user.role),
    }


@router.post("/login", summary="Войти")
def login(payload: LoginRequest, request: Request, session: DbSession = Depends(get_session)) -> dict:
    # Ограничение попыток: пароли у четверых сотрудников, перебор недопустим.
    login_limiter.check(client_ip(request))

    user = session.scalars(select(User).where(User.email == payload.email.strip().lower())).first()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        # Один и тот же ответ на «нет пользователя» и «неверный пароль»:
        # иначе можно узнать, кто заведён в системе.
        raise HTTPException(status_code=401, detail="Неверная почта или пароль.")

    token = new_session_token()
    session.add(
        Session(
            user_id=user.id,
            token_hash=token_fingerprint(token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS),
        )
    )
    session.commit()
    return {"token": token, "user": user_payload(user)}


@router.post("/logout", summary="Выйти")
def logout(
    actor: Actor = Depends(current_actor), session: DbSession = Depends(get_session)
) -> dict:
    if actor.session_id:
        record = session.get(Session, actor.session_id)
        if record:
            session.delete(record)
            session.commit()
    return {"ok": True}


@router.post("/password", summary="Сменить свой пароль")
def change_password(
    payload: PasswordChange,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    """Меняет пароль текущего сотрудника.

    Восстановления по почте нет и не будет: адреса в системе служат логинами,
    ящиков за ними не стоит. Поэтому свой пароль сотрудник меняет, зная
    старый, а забытый сбрасывает руководитель через scripts/set_password.py.
    """
    if actor.user is None:
        raise HTTPException(status_code=403, detail="Служебный доступ пароль не меняет.")

    if not verify_password(payload.current_password, actor.user.password_hash):
        raise HTTPException(status_code=400, detail="Текущий пароль неверен.")

    try:
        actor.user.password_hash = hash_password(payload.new_password)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    # Остальные сессии закрываются: пароль меняют в том числе тогда, когда
    # прежний мог утечь, и старый вход не должен пережить смену.
    for record in session.scalars(select(Session).where(Session.user_id == actor.user.id)):
        if record.id != actor.session_id:
            session.delete(record)
    session.commit()
    return {"ok": True}


@router.get("/me", summary="Кто я")
def me(actor: Actor = Depends(current_actor)) -> dict:
    if actor.user:
        return user_payload(actor.user)
    return {"id": None, "email": None, "name": "Служебный доступ", "role": actor.role,
            "role_title": ROLES.get(actor.role, actor.role)}
