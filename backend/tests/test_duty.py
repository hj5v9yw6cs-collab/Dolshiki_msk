"""Госпошлина по статьям 333.19 и 333.36 НК.

Проверяется не «функция что-то вернула», а конкретные суммы из закона.
Ошибка в такой таблице выглядит правдоподобно — число выходит похожее на
правду, и заметить его в готовом иске нельзя.
"""

from decimal import Decimal

import pytest

from app.core.duty import MAXIMUM, SCALE, duty_for_claim, duty_for_value


@pytest.mark.parametrize("value, expected", [
    (0, 0),
    (1, 4_000),
    (50_000, 4_000),
    (100_000, 4_000),          # верх первой ступени
    (250_000, 8_500),          # 4 000 + 3 % от 150 000
    (300_000, 10_000),
    (400_000, 12_500),         # 10 000 + 2,5 % от 100 000
    (1_000_000, 25_000),
    (1_500_000, 30_000),       # 25 000 + 1 % от 500 000
    (8_000_000, 80_000),
    (100_000_000, 314_000),
])
def test_scale_matches_the_code(value, expected):
    assert duty_for_value(Decimal(value)) == Decimal(expected)


def test_scale_has_no_jumps_at_the_boundaries():
    """Фиксированная часть ступени равна пошлине на её нижней границе.

    Разрыв здесь означал бы опечатку в таблице: цена иска в рубль выше
    порога давала бы пошлину заметно другого размера.
    """
    for threshold, base, _ in SCALE[1:]:
        assert duty_for_value(threshold) == base, f"разрыв на {threshold}"


def test_the_law_caps_the_largest_claims():
    assert duty_for_value(Decimal(10_000_000_000)) == MAXIMUM


def test_consumer_pays_nothing_up_to_a_million():
    duty = duty_for_claim(Decimal("999999.99"))

    assert duty.amount == 0
    assert duty.exempt
    assert "защите прав потребителей" in duty.explanation


def test_consumer_pays_only_on_the_excess():
    """Пункт 3 статьи 333.36: пошлина уменьшается на пошлину с миллиона."""
    duty = duty_for_claim(Decimal(1_500_000))

    assert duty.amount == Decimal(5_000)   # 30 000 − 25 000
    assert not duty.exempt
    assert duty.full == Decimal(30_000)


def test_a_non_consumer_pays_the_whole_scale():
    assert duty_for_claim(Decimal(1_500_000), consumer=False).amount == Decimal(30_000)


def test_missing_claim_value_is_not_an_error():
    """Пустая карточка не должна ронять расчёт — она должна давать ноль."""
    assert duty_for_claim(None).amount == 0
