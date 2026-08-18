"""Извлечение реквизитов из текста документа.

Всё, что здесь получается, — это ПРЕДЛОЖЕНИЕ для карточки дела, а не
готовые данные. Юрист подтверждает или правит; система ничего не
подставляет молча.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
    "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

NUMBER_RE = re.compile(
    r"(?:договор[а-я]*|дду)[^\n№]{0,60}№\s*([A-Za-zА-Яа-я0-9][A-Za-zА-Яа-я0-9\-/\.]{1,30})",
    re.IGNORECASE,
)
DOTTED_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
WORDED_DATE_RE = re.compile(
    r"[«\"]?(\d{1,2})[»\"]?\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", re.IGNORECASE
)
PRICE_RE = re.compile(
    r"(\d{1,3}(?:[  ]\d{3}){1,4}(?:[.,]\d{2})?)\s*(?:руб|₽|рублей)", re.IGNORECASE
)
FLAT_RE = re.compile(
    r"(?:квартир[а-я]{0,2}|помещени[а-я]{0,2})[^\n]{0,40}?(?:№|условный номер)\s*([0-9]{1,4}[А-Яа-я]?)",
    re.IGNORECASE,
)
# В хвосте нельзя запрещать точку: сама дата пишется через точки (30.12.2021).
TRANSFER_RE = re.compile(
    r"передать[^.]{0,200}?(?:не позднее|в срок до|до)\s+([^,;\n]{4,60})", re.IGNORECASE
)


@dataclass
class Requisites:
    contract_number: Optional[str] = None
    contract_date: Optional[date] = None
    contract_price: Optional[Decimal] = None
    apartment: Optional[str] = None
    due_date: Optional[date] = None

    def as_dict(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        if self.contract_number:
            result["contract_number"] = self.contract_number
        if self.contract_date:
            result["contract_date"] = self.contract_date.isoformat()
        if self.contract_price is not None:
            result["contract_price"] = str(self.contract_price)
        if self.apartment:
            result["apartment"] = self.apartment
        if self.due_date:
            result["due_date"] = self.due_date.isoformat()
        return result

    @property
    def is_empty(self) -> bool:
        return not self.as_dict()


def parse_date(text: str) -> Optional[date]:
    """Дата в формате 12.05.2021 или «12» мая 2021 года."""
    match = DOTTED_DATE_RE.search(text)
    if match:
        day, month, year = (int(part) for part in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    match = WORDED_DATE_RE.search(text)
    if match:
        day, month_name, year = match.groups()
        month = MONTHS.get(month_name.lower())
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                return None
    return None


def parse_price(text: str) -> Optional[Decimal]:
    match = PRICE_RE.search(text)
    if not match:
        return None
    raw = match.group(1).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def extract(text: str, doc_type: str = "") -> Requisites:
    """Реквизиты из текста. Пустые поля — норма, а не ошибка."""
    if not text:
        return Requisites()

    result = Requisites()

    number = NUMBER_RE.search(text)
    if number:
        result.contract_number = number.group(1).strip(" .,;")

    # Дата договора ищется в начале: там она стоит в шапке.
    result.contract_date = parse_date(text[:2000])
    result.contract_price = parse_price(text)

    flat = FLAT_RE.search(text)
    if flat:
        result.apartment = flat.group(1)

    transfer = TRANSFER_RE.search(text)
    if transfer:
        result.due_date = parse_date(transfer.group(1))

    # Для не-договоров реквизиты договора не предлагаем: в претензии или
    # решении суда те же числа значат совсем другое.
    if doc_type not in ("ddu", "ddu_amendment", "assignment", ""):
        result.contract_price = None
        result.due_date = None

    return result
