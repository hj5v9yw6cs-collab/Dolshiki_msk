"""Структуры результата расчёта.

Результат намеренно подробный: юрист должен видеть не только итог, но и
каждый сегмент с его ставкой и правовым основанием — эта таблица идёт
приложением к исковому заявлению.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional

RATE_MODES = (
    "on_obligation_date",  # ставка на день исполнения обязательства (по умолчанию)
    "on_actual_date",      # на дату фактической передачи / на сегодня
    "on_claim_date",       # на дату подачи иска
    "manual",              # введена вручную
    "per_segment",         # своя действующая ставка на каждый сегмент
)

RATE_MODE_TITLES = {
    "on_obligation_date": "ставка на день исполнения обязательства по договору",
    "on_actual_date": "ставка на дату фактической передачи объекта",
    "on_claim_date": "ставка на дату подачи иска",
    "manual": "ставка введена вручную",
    "per_segment": "по каждому периоду — своя действовавшая ставка",
}


@dataclass
class Segment:
    """Один расчётный отрезок: непрерывный период с одной ставкой."""

    start: date
    end: date
    days: int
    rate: Decimal
    rate_source_date: date
    multiplier: Decimal
    divisor: Decimal
    base_amount: Decimal
    amount: Decimal
    rate_before_cap: Optional[Decimal] = None
    cap_basis: Optional[str] = None

    @property
    def is_capped(self) -> bool:
        return self.rate_before_cap is not None


@dataclass
class ExcludedPeriod:
    """Период, исключённый из расчёта (мораторий)."""

    start: date
    end: date
    days: int
    basis: str
    note: str = ""


@dataclass
class LineItem:
    """Строка итоговой суммы: неустойка, штраф, моральный вред, расходы."""

    code: str
    title: str
    amount: Decimal
    basis: str = ""
    note: str = ""


@dataclass
class CalculationResult:
    mode: str
    period_start: Optional[date]
    period_end: Optional[date]
    total_days: int
    segments: List[Segment]
    excluded: List[ExcludedPeriod]
    lines: List[LineItem]
    total: Decimal
    rate_mode: str
    rate_mode_title: str
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    disclaimer: str = ""
    config_version: int = 0

    def line(self, code: str) -> Optional[LineItem]:
        for item in self.lines:
            if item.code == code:
                return item
        return None

    def amount_of(self, code: str) -> Decimal:
        item = self.line(code)
        return item.amount if item else Decimal("0.00")
