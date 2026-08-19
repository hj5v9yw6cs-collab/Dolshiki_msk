"""Подключение к БД.

По умолчанию SQLite в файле — чтобы систему можно было поднять одной
командой на этапе запуска. Переменная DATABASE_URL переключает на
PostgreSQL без правки кода (см. .env.example).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect
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


def _add_missing_columns() -> None:
    """Дописывает в существующие таблицы новые необязательные колонки.

    create_all создаёт недостающие таблицы, но не колонки: после обновления
    версии старая база осталась бы без новых полей, и приложение падало бы
    на первом же запросе. Alembic на одну машину и четырёх сотрудников —
    инструмент тяжелее задачи, а добавление nullable-колонки данных не
    трогает и повторный запуск переживает.

    Колонка без значения по умолчанию и с NOT NULL так не добавляется —
    такие изменения остаются ручной работой и здесь пропускаются.
    """
    inspector = inspect(engine)
    present = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in present:
                continue
            have = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have or not column.nullable:
                    continue
                sql_type = column.type.compile(engine.dialect)
                connection.exec_driver_sql(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {sql_type}'
                )


def init_db() -> None:
    from . import models  # noqa: F401  — регистрация таблиц

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
