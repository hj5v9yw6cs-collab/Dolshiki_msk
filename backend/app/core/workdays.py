"""Рабочие и нерабочие дни для статьи 193 ГК РФ.

Если срок исполнения обязательства выпал на нерабочий день, он
переносится на ближайший следующий рабочий день — и просрочка начинается
на день позже. Без этого расчёт завышает сумму, а застройщик в суде
поправит нас первым же возражением.

Что считать нерабочим днём, задаётся конфигом: суббота и воскресенье
плюс праздники по ст. 112 ТК РФ. Ежегодные переносы выходных
постановлениями правительства сюда не заложены — их вносит юрист
списком, поэтому блок помечен как требующий проверки.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Set

# Больше недели подряд нерабочих дней не бывает даже в январе,
# но запас нужен на случай странного конфига.
MAX_SHIFT_DAYS = 30


@dataclass(frozen=True)
class WorkdayRule:
    apply_article_193: bool
    weekend_weekdays: Set[int]
    holidays_every_year: Set[str]
    extra_non_working: Set[date]
    working_exceptions: Set[date]
    basis: str
    note: str = ""
    requires_lawyer_review: bool = True

    def is_non_working(self, day: date) -> bool:
        # Явное исключение сильнее всех прочих правил: так вносят
        # рабочие субботы из производственного календаря.
        if day in self.working_exceptions:
            return False
        if day in self.extra_non_working:
            return True
        if day.weekday() in self.weekend_weekdays:
            return True
        return day.strftime("%m-%d") in self.holidays_every_year

    def next_working_day(self, day: date) -> date:
        if not self.apply_article_193:
            return day
        shifted = day
        for _ in range(MAX_SHIFT_DAYS):
            if not self.is_non_working(shifted):
                return shifted
            shifted += timedelta(days=1)
        return day  # конфиг явно сломан — не зацикливаемся


def parse_workdays(data: Dict[str, Any]) -> WorkdayRule:
    block = data.get("working_days") or {}

    def dates(key: str) -> Set[date]:
        result: Set[date] = set()
        for value in block.get(key, []) or []:
            try:
                result.add(date.fromisoformat(value))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"working_days.{key}: некорректная дата {value!r}") from exc
        return result

    return WorkdayRule(
        apply_article_193=bool(block.get("apply_article_193", False)),
        weekend_weekdays=set(block.get("weekend_weekdays", [5, 6])),
        holidays_every_year=set(block.get("holidays_every_year", []) or []),
        extra_non_working=dates("extra_non_working"),
        working_exceptions=dates("working_exceptions"),
        basis=block.get("basis", ""),
        note=block.get("note", ""),
        requires_lawyer_review=bool(block.get("requires_lawyer_review", True)),
    )
