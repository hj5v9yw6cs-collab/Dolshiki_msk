#!/usr/bin/env python
"""Заводит сотрудника в системе.

    ./.venv/bin/python scripts/create_user.py ivan@example.ru "Иван Петров" manager

Пароль спрашивается интерактивно и в истории команд не остаётся.
Роли: manager (руководитель, видит деньги) и lawyer (юрист).
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.casework import ROLES  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import User  # noqa: E402


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2

    email, name, role = sys.argv[1].strip().lower(), sys.argv[2].strip(), sys.argv[3].strip()
    if role not in ROLES:
        print(f"Роль должна быть одной из: {', '.join(ROLES)}")
        return 2

    init_db()
    session = SessionLocal()
    try:
        if session.scalars(select(User).where(User.email == email)).first():
            print(f"Пользователь {email} уже заведён.")
            return 1

        password = getpass.getpass("Пароль (минимум 8 символов): ")
        if password != getpass.getpass("Повторите пароль: "):
            print("Пароли не совпали.")
            return 1

        try:
            password_hash = hash_password(password)
        except ValueError as error:
            print(error)
            return 1

        session.add(User(email=email, name=name, role=role, password_hash=password_hash))
        session.commit()
        print(f"Готово: {name} <{email}>, роль — {ROLES[role]}.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
