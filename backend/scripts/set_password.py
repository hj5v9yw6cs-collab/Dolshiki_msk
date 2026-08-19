#!/usr/bin/env python
"""Задаёт сотруднику новый пароль.

    docker compose exec app python scripts/set_password.py urist@dolshikirf.ru

Нужен, когда пароль забыт: восстановления по почте в системе нет, адреса
служат логинами и ящиков за ними не стоит. Свой пароль, если он известен,
сотрудник меняет сам в кабинете.

Пароль спрашивается интерактивно и в истории команд не остаётся. Все
открытые сессии сотрудника закрываются: после сброса нужно войти заново.
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Session, User  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    email = sys.argv[1].strip().lower()

    init_db()
    session = SessionLocal()
    try:
        user = session.scalars(select(User).where(User.email == email)).first()
        if user is None:
            print(f"Сотрудник {email} не найден.")
            return 1

        password = getpass.getpass("Новый пароль (минимум 8 символов): ")
        if password != getpass.getpass("Повторите пароль: "):
            print("Пароли не совпали.")
            return 1

        try:
            user.password_hash = hash_password(password)
        except ValueError as error:
            print(error)
            return 1

        closed = 0
        for record in session.scalars(select(Session).where(Session.user_id == user.id)):
            session.delete(record)
            closed += 1
        session.commit()

        print(f"Готово: пароль {user.name} <{user.email}> изменён.")
        if closed:
            print(f"Закрыто открытых сессий: {closed} — потребуется войти заново.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
