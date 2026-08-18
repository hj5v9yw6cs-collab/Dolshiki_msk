"""Подключение к БД.

По умолчанию SQLite в файле — чтобы систему можно было поднять одной
командой на этапе запуска. Переменная DATABASE_URL переключает на
PostgreSQL без правки кода (см. .env.example).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .env import env

DATA_DIR = Path(env("DATA_DIR", str(Path(__file__).resolve().parents[1] / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = env("DATABASE_URL", f"sqlite:///{DATA_DIR / 'app.db'}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from . import models  # noqa: F401  — регистрация таблиц

    Base.metadata.create_all(bind=engine)
