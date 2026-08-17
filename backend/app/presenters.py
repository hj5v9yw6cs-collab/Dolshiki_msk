"""Преобразование результата расчёта в JSON и в человекочитаемый вид.

Суммы отдаём строками (не float), чтобы копейки не поехали при передаче
через JSON. Рядом кладём отформатированное значение для вывода в UI и
готовую строку формулы — её же вставляем в таблицу-приложение к иску.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from .core.calculator.models import CalculationResult, Segment

RU_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def format_money(value: Decimal) -> str:
    """1234567.5 -> '1 234 567,50'"""
    quantized = Decimal(value).quantize(Decimal("0.01"))
    whole, _, fraction = f"{abs(quantized):.2f}".partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    sign = "-" if quantized < 0 else ""
    return f"{sign}{' '.join(groups)},{fraction}"


def format_rate(value: Decimal) -> str:
    text = f"{Decimal(value).normalize():f}"
    return text.replace(".", ",")


def format_date(value) -> Optional[str]:
    return value.strftime("%d.%m.%Y") if value else None


def plural_days(count: int) -> str:
    if 11 <= count % 100 <= 14:
        return "дней"
    last = count % 10
    if last == 1:
        return "день"
    if 2 <= last <= 4:
        return "дня"
    return "дней"


def segment_formula(segment: Segment) -> str:
    """Строка расчёта сегмента — как её увидит суд."""
    multiplier = ""
    if segment.multiplier != 1:
        multiplier = f" × {format_rate(segment.multiplier)}"
    return (
        f"{format_money(segment.base_amount)} × {segment.days} {plural_days(segment.days)}"
        f" × {format_rate(segment.rate)}% / {format_rate(segment.divisor)}{multiplier}"
        f" = {format_money(segment.amount)} ₽"
    )


def segment_to_dict(segment: Segment) -> Dict[str, Any]:
    return {
        "start": segment.start.isoformat(),
        "end": segment.end.isoformat(),
        "start_display": format_date(segment.start),
        "end_display": format_date(segment.end),
        "days": segment.days,
        "days_display": f"{segment.days} {plural_days(segment.days)}",
        "rate": str(segment.rate),
        "rate_display": f"{format_rate(segment.rate)}%",
        "rate_source_date": segment.rate_source_date.isoformat(),
        "rate_source_date_display": format_date(segment.rate_source_date),
        "rate_before_cap": str(segment.rate_before_cap) if segment.is_capped else None,
        "cap_basis": segment.cap_basis,
        "multiplier": str(segment.multiplier),
        "divisor": str(segment.divisor),
        "base_amount": str(segment.base_amount),
        "amount": str(segment.amount),
        "amount_display": format_money(segment.amount),
        "formula": segment_formula(segment),
    }


def result_to_dict(result: CalculationResult) -> Dict[str, Any]:
    return {
        "mode": result.mode,
        "period": {
            "start": result.period_start.isoformat() if result.period_start else None,
            "end": result.period_end.isoformat() if result.period_end else None,
            "start_display": format_date(result.period_start),
            "end_display": format_date(result.period_end),
            "days": result.total_days,
            "days_display": f"{result.total_days} {plural_days(result.total_days)}",
        },
        "segments": [segment_to_dict(segment) for segment in result.segments],
        "excluded": [
            {
                "start": item.start.isoformat(),
                "end": item.end.isoformat(),
                "start_display": format_date(item.start),
                "end_display": format_date(item.end),
                "days": item.days,
                "days_display": f"{item.days} {plural_days(item.days)}",
                "basis": item.basis,
                "note": item.note,
            }
            for item in result.excluded
        ],
        "lines": [
            {
                "code": line.code,
                "title": line.title,
                "amount": str(line.amount),
                "amount_display": format_money(line.amount),
                "basis": line.basis,
                "note": line.note,
            }
            for line in result.lines
        ],
        "total": str(result.total),
        "total_display": format_money(result.total),
        "rate_mode": result.rate_mode,
        "rate_mode_title": result.rate_mode_title,
        "warnings": result.warnings,
        "notes": result.notes,
        "disclaimer": result.disclaimer,
        "config_version": result.config_version,
    }
