"""Схемы запросов API."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class ExpenseIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(ge=0)
    code: str = Field(default="expense", max_length=32)


class DelayRequest(BaseModel):
    """Режим 1 — просрочка передачи объекта."""

    contract_price: Decimal = Field(gt=0, description="Цена договора по ДДУ, ₽")
    due_date: date = Field(description="Срок передачи объекта по договору")
    actual_date: Optional[date] = Field(
        default=None, description="Дата фактической передачи; пусто — объект не передан"
    )
    is_individual: bool = True
    rate_mode: str = ""
    manual_rate: Optional[Decimal] = Field(default=None, ge=0, le=1000)
    claim_date: Optional[date] = None
    moral_harm: Decimal = Field(default=Decimal("0"), ge=0)
    include_consumer_penalty: bool = True
    expenses: List[ExpenseIn] = Field(default_factory=list, max_length=20)
    source: str = Field(default="widget", max_length=64)


class DefectsRequest(BaseModel):
    """Режим 2 — недостатки отделки."""

    repair_cost: Decimal = Field(gt=0, description="Стоимость устранения по заключению эксперта, ₽")
    demand_served_date: date = Field(description="Дата вручения требования застройщику")
    satisfied_date: Optional[date] = Field(
        default=None, description="Дата удовлетворения требования; пусто — не удовлетворено"
    )
    expertise_cost: Decimal = Field(default=Decimal("0"), ge=0)
    rate_mode: str = ""
    manual_rate: Optional[Decimal] = Field(default=None, ge=0, le=1000)
    claim_date: Optional[date] = None
    moral_harm: Decimal = Field(default=Decimal("0"), ge=0)
    include_consumer_penalty: bool = True
    include_repair_cost_in_total: bool = True
    expenses: List[ExpenseIn] = Field(default_factory=list, max_length=20)
    source: str = Field(default="widget", max_length=64)


class LeadRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    phone: str = Field(min_length=6, max_length=32)
    email: Optional[str] = Field(default=None, max_length=200)
    topic: str = Field(default="neustoyka", max_length=32)
    region: Optional[str] = Field(default=None, max_length=32)
    project: Optional[str] = Field(default=None, max_length=200)
    comment: Optional[str] = Field(default=None, max_length=2000)
    calculation_id: Optional[str] = Field(default=None, max_length=36)
    page_url: Optional[str] = Field(default=None, max_length=1000)
    source: str = Field(default="calculator", max_length=64)

    # 152-ФЗ: без согласия заявка не принимается
    consent: bool = False
    consent_policy_version: str = Field(default="1.0", max_length=32)

    # Ловушка для ботов: поле скрыто в форме и должно оставаться пустым
    website: str = Field(default="", max_length=200)

    @field_validator("phone")
    @classmethod
    def phone_must_contain_digits(cls, value: str) -> str:
        digits = [char for char in value if char.isdigit()]
        if len(digits) < 6:
            raise ValueError("Телефон указан некорректно")
        return value.strip()


class ConfigUpdateRequest(BaseModel):
    config: dict
    author: str = Field(min_length=3, max_length=200)
    comment: str = Field(default="", max_length=1000)


# --- Фаза 2: доступ и дела --------------------------------------------------


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class PasswordChange(BaseModel):
    """Смена своего пароля. Длину проверяет hash_password — там же, где она
    задана для всех остальных способов завести пароль."""

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class CaseCreate(BaseModel):
    """Создание дела. Клиент заводится тут же — отдельный справочник
    на потоке в 30 дел в месяц только добавляет кликов."""

    client_name: str = Field(min_length=2, max_length=300)
    client_phone: str = Field(min_length=6, max_length=32)
    client_email: Optional[str] = Field(default=None, max_length=200)

    service_type: str = Field(default="delay", max_length=20)
    region: str = Field(default="msk", max_length=32)
    stage: str = Field(default="new", max_length=24)
    lawyer_id: Optional[str] = Field(default=None, max_length=36)

    developer_name: Optional[str] = Field(default=None, max_length=300)
    project: Optional[str] = Field(default=None, max_length=300)
    apartment: Optional[str] = Field(default=None, max_length=100)

    contract_number: Optional[str] = Field(default=None, max_length=100)
    contract_date: Optional[date] = None
    contract_price: Optional[Decimal] = Field(default=None, ge=0)
    due_date: Optional[date] = None
    actual_transfer_date: Optional[date] = None

    calculation_id: Optional[str] = Field(default=None, max_length=36)
    lead_id: Optional[str] = Field(default=None, max_length=36)
    comment: Optional[str] = Field(default=None, max_length=4000)


class CaseUpdate(BaseModel):
    """Частичное обновление: приходят только изменённые поля."""

    model_config = {"extra": "forbid"}

    client_name: Optional[str] = Field(default=None, max_length=300)
    client_phone: Optional[str] = Field(default=None, max_length=32)
    client_email: Optional[str] = Field(default=None, max_length=200)

    service_type: Optional[str] = Field(default=None, max_length=20)
    region: Optional[str] = Field(default=None, max_length=32)
    lawyer_id: Optional[str] = Field(default=None, max_length=36)
    developer_name: Optional[str] = Field(default=None, max_length=300)
    project: Optional[str] = Field(default=None, max_length=300)
    apartment: Optional[str] = Field(default=None, max_length=100)

    contract_number: Optional[str] = Field(default=None, max_length=100)
    contract_date: Optional[date] = None
    contract_price: Optional[Decimal] = Field(default=None, ge=0)
    due_date: Optional[date] = None
    actual_transfer_date: Optional[date] = None

    claim_sent_on: Optional[date] = None
    claim_response_deadline: Optional[date] = None

    court_name: Optional[str] = Field(default=None, max_length=300)
    court_case_number: Optional[str] = Field(default=None, max_length=100)
    next_hearing_on: Optional[date] = None
    appeal_deadline: Optional[date] = None

    amount_claimed: Optional[Decimal] = Field(default=None, ge=0)
    amount_awarded: Optional[Decimal] = Field(default=None, ge=0)
    amount_received: Optional[Decimal] = Field(default=None, ge=0)
    fee: Optional[Decimal] = Field(default=None, ge=0)

    comment: Optional[str] = Field(default=None, max_length=4000)


class StageChange(BaseModel):
    stage: str = Field(max_length=24)
    comment: str = Field(default="", max_length=1000)


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class LeadConvert(BaseModel):
    lawyer_id: Optional[str] = Field(default=None, max_length=36)
    service_type: Optional[str] = Field(default=None, max_length=20)


class DocumentUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    doc_type: Optional[str] = Field(default=None, max_length=32)
    doc_date: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=2000)
