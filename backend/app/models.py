"""Таблицы Фазы 1.

Сохраняем расчёты отдельно от заявок: расчёт может быть анонимным
(человек посчитал и ушёл), а заявка — привязываться к ранее сделанному
расчёту, чтобы юрист видел, с какими цифрами пришёл клиент.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, String, Text
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


# ---------------------------------------------------------------------------
# Фаза 2: пользователи и ведение дел
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(16), default="lawyer")  # manager | lawyer
    password_hash: Mapped[str] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(default=True)

    cases: Mapped[list["Case"]] = relationship(back_populates="lawyer")


class Session(Base):
    """Сессия входа. В базе лежит хеш токена, не сам токен."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    user: Mapped[User] = relationship()


class Developer(Base):
    """Застройщик."""

    __tablename__ = "developers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    name: Mapped[str] = mapped_column(String(300), index=True)
    # Нормализованное имя для поиска дублей: SQL-функция lower() в SQLite
    # не работает с кириллицей, поэтому ключ считаем в Python.
    name_key: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ogrn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class TypeHint(Base):
    """Слово из имени файла и тип документа, которым его назвал юрист.

    Копится из исправлений: правила ошиблись, человек поправил — значит,
    в имени было слово, по которому он понял тип сразу.
    """

    __tablename__ = "type_hints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    word: Mapped[str] = mapped_column(String(60), index=True)
    doc_type: Mapped[str] = mapped_column(String(32), index=True)
    weight: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    full_name: Mapped[str] = mapped_column(String(300), index=True)
    phone: Mapped[str] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    region: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Паспортные данные и номера нужны для иска: суд требует их в шапке.
    # Заполняются из ДДУ, где они есть в реквизитах сторон.
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    passport: Mapped[str | None] = mapped_column(String(200), nullable=True)
    snils: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inn: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)

    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    cases: Mapped[list["Case"]] = relationship(back_populates="client")


class Case(Base):
    """Дело — центральная сущность системы."""

    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    client_id: Mapped[str] = mapped_column(String(36), ForeignKey("clients.id"))
    client: Mapped[Client] = relationship(back_populates="cases")

    developer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("developers.id"), nullable=True)
    developer: Mapped[Developer | None] = relationship()

    lawyer_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    lawyer: Mapped[User | None] = relationship(back_populates="cases")

    service_type: Mapped[str] = mapped_column(String(20), default="delay")
    region: Mapped[str] = mapped_column(String(32), default="msk")
    stage: Mapped[str] = mapped_column(String(24), default="new", index=True)

    project: Mapped[str | None] = mapped_column(String(300), nullable=True)  # ЖК
    apartment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    object_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    area: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    contract_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contract_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_transfer_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    claim_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    claim_response_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Почтовые идентификаторы: по ним заказывается отчёт об отслеживании,
    # который подшивается к иску.
    claim_track_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lawsuit_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    lawsuit_track_number: Mapped[str | None] = mapped_column(String(40), nullable=True)

    court_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    court_case_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    next_hearing_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    appeal_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)

    amount_claimed: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Просят в иске отдельными требованиями, и обе суммы попадают в шаблон.
    moral_damage: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    duty: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    amount_awarded: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    amount_received: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    calculation_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("calculations.id"), nullable=True)
    lead_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("leads.id"), nullable=True)

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["CaseEvent"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="CaseEvent.created_at.desc()"
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="Document.created_at.desc()"
    )


class CaseEvent(Base):
    """Лента дела: смена стадии, правки полей, заметки юриста."""

    __tablename__ = "case_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("cases.id"), index=True)
    case: Mapped[Case] = relationship(back_populates="events")

    author_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(200), default="система")
    kind: Mapped[str] = mapped_column(String(16), default="note")  # stage | note | field | system
    text: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------------------
# Фаза 3: документы по делу
# ---------------------------------------------------------------------------


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("cases.id"), index=True)
    case: Mapped["Case"] = relationship(back_populates="documents")

    original_name: Mapped[str] = mapped_column(String(300))
    stored_name: Mapped[str] = mapped_column(String(300))
    # Путь относительно папки дела: 01_Договор/Petrov_2026-001_DDU.pdf
    relative_path: Mapped[str] = mapped_column(String(500))
    folder: Mapped[str] = mapped_column(String(40), default="99_Прочее")

    doc_type: Mapped[str] = mapped_column(String(32), default="other", index=True)
    doc_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    size_bytes: Mapped[int] = mapped_column(default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)

    # Как система определила тип и почему.
    confidence: Mapped[float] = mapped_column(default=0.0)
    needs_review: Mapped[bool] = mapped_column(default=True)
    detected_by: Mapped[str] = mapped_column(String(16), default="rules")  # rules | manual
    signals: Mapped[str] = mapped_column(Text, default="")
    is_scan: Mapped[bool] = mapped_column(default=False)

    # Реквизиты, извлечённые из текста, — предложение для карточки дела.
    extracted: Mapped[dict] = mapped_column(JSON, default=dict)
    extracted_applied: Mapped[bool] = mapped_column(default=False)

    uploaded_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    uploaded_by_name: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentAccess(Base):
    """Журнал доступа к файлам клиентов — требование при обработке ПДн."""

    __tablename__ = "document_access"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), index=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_name: Mapped[str] = mapped_column(String(200), default="")
    action: Mapped[str] = mapped_column(String(16), default="download")  # download | delete
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
