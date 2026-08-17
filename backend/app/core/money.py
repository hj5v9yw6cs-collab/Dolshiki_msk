"""Денежная арифметика.

Все суммы внутри расчёта — Decimal. Округление до копеек банковское
(ROUND_HALF_EVEN) и выполняется только на границах: при выводе строки
расчёта и при подсчёте итога. Промежуточные умножения не округляются,
чтобы не накапливать ошибку по сегментам.
"""

from decimal import Decimal, ROUND_HALF_EVEN

KOPECK = Decimal("0.01")


def money(value) -> Decimal:
    """Приводит вход к Decimal без потери точности на float."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_kopecks(value: Decimal) -> Decimal:
    """Банковское округление до копеек."""
    return money(value).quantize(KOPECK, rounding=ROUND_HALF_EVEN)


def percent_of(base: Decimal, percent) -> Decimal:
    return money(base) * money(percent) / Decimal(100)
