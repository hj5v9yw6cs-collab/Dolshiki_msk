"""Таблицы Фазы 1.

Сохраняем расчёты отдельно от заявок: расчёт может быть анонимным
(человек посчитал и ушёл), а заявка — привязываться к ранее сделанному
расчёту, чтобы юрист видел, с какими цифрами пришёл клиент.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Calculation(Base):
    __tablename__ = "calculations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    mode: Mapped[str] = mapped_column(String(16))
    inputs: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    total: Mapped[float] = mapped_column(Numeric(18, 2))
    config_version: Mapped[int] = mapped_column(default=0)
    source: Mapped[str] = mapped_column(String(64), default="widget")

    leads: Mapped[list["Lead"]] = relationship(back_populates="calculation")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    topic: Mapped[str] = mapped_column(String(32), default="neustoyka")
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)
    project: Mapped[str | None] = mapped_column(String(200), nullable=True)  # ЖК / объект
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    calculation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("calculations.id"), nullable=True
    )
    calculation: Mapped[Calculation | None] = relationship(back_populates="leads")

    # 152-ФЗ: фиксируем факт согласия на обработку персональных данных
    consent_given: Mapped[bool] = mapped_column(default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consent_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    source: Mapped[str] = mapped_column(String(64), default="calculator")
    page_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="new")


class ConfigChange(Base):
    """Журнал правок юридического конфига: кто, когда, что поменял."""

    __tablename__ = "config_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    author: Mapped[str] = mapped_column(String(200))
    version_before: Mapped[int] = mapped_column(default=0)
    version_after: Mapped[int] = mapped_column(default=0)
    diff_summary: Mapped[str] = mapped_column(Text, default="")
    snapshot: Mapped[dict] = mapped_column(JSON)
