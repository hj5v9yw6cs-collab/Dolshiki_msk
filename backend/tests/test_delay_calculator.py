"""Тесты режима 1 — неустойка за просрочку передачи объекта.

Восемь обязательных случаев из ТЗ идут первыми и подписаны номерами.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.core.calculator import CalculationError, DelayInput, ExpenseInput, calculate_delay

PRICE = Decimal("1000000")


def run(config, **kwargs):
    defaults = dict(contract_price=PRICE, is_individual=True, today=date(2026, 1, 1))
    defaults.update(kwargs)
    return calculate_delay(DelayInput(**defaults), config)


# --- Случай 1: просрочка целиком внутри моратория ---------------------------


def test_case1_delay_fully_inside_moratorium_is_zero(config):
    result = run(config, due_date=date(2022, 6, 10), actual_date=date(2022, 7, 10))

    assert result.segments == []
    assert result.total_days == 0
    assert result.amount_of("neustoyka") == Decimal("0.00")
    assert result.total == Decimal("0.00")
    assert len(result.excluded) == 1
    assert result.excluded[0].basis == "тестовый мораторий"


# --- Случай 2: просрочка целиком до моратория -------------------------------


def test_case2_delay_before_moratorium_single_rate(config):
    result = run(config, due_date=date(2022, 1, 10), actual_date=date(2022, 2, 9))

    assert len(result.segments) == 1
    segment = result.segments[0]
    assert (segment.start, segment.end) == (date(2022, 1, 11), date(2022, 2, 9))
    assert segment.days == 30
    assert segment.rate == Decimal("10.0")
    # 1 000 000 × 30 × 10% / 300 × 2
    assert segment.amount == Decimal("20000.00")
    assert result.total == Decimal("20000.00")
    assert result.excluded == []


# --- Случай 3: мораторий разрывает просрочку на два сегмента -----------------


def test_case3_moratorium_splits_delay_into_two_segments(config):
    result = run(config, due_date=date(2022, 5, 1), actual_date=date(2022, 9, 30))

    assert len(result.segments) == 2
    first, second = result.segments
    assert (first.start, first.end, first.days) == (date(2022, 5, 2), date(2022, 5, 31), 30)
    assert (second.start, second.end, second.days) == (date(2022, 9, 1), date(2022, 9, 30), 30)
    assert result.total_days == 60
    assert first.amount == Decimal("20000.00")
    assert second.amount == Decimal("20000.00")
    assert result.amount_of("neustoyka") == Decimal("40000.00")

    assert len(result.excluded) == 1
    excluded = result.excluded[0]
    assert (excluded.start, excluded.end) == (date(2022, 6, 1), date(2022, 8, 31))
    assert excluded.days == 92


# --- Случай 4: ставка менялась внутри периода просрочки ---------------------


def test_case4_rate_change_inside_period_segments_by_rate(config):
    result = run(
        config,
        due_date=date(2021, 12, 1),
        actual_date=date(2022, 1, 31),
        rate_mode="per_segment",
    )

    assert len(result.segments) == 2
    first, second = result.segments
    assert (first.start, first.end, first.days) == (date(2021, 12, 2), date(2021, 12, 31), 30)
    assert first.rate == Decimal("6.0")
    assert first.amount == Decimal("12000.00")

    assert (second.start, second.end, second.days) == (date(2022, 1, 1), date(2022, 1, 31), 31)
    assert second.rate == Decimal("10.0")
    assert second.amount == Decimal("20666.67")

    assert result.amount_of("neustoyka") == Decimal("32666.67")


def test_case4_fixed_rate_mode_does_not_split_by_rate(config):
    """В режиме фиксированной ставки период не дробится на ставочные куски."""
    result = run(config, due_date=date(2021, 12, 1), actual_date=date(2022, 1, 31))

    assert len(result.segments) == 1
    assert result.segments[0].rate == Decimal("6.0")  # ставка на 01.12.2021
    assert result.segments[0].days == 61


# --- Случай 5: физлицо против юрлица ---------------------------------------


def test_case5_individual_multiplier_is_double_legal_entity(config):
    kwargs = dict(due_date=date(2022, 1, 10), actual_date=date(2022, 2, 9))
    individual = run(config, is_individual=True, **kwargs)
    legal_entity = run(config, is_individual=False, **kwargs)

    assert individual.segments[0].multiplier == Decimal("2")
    assert legal_entity.segments[0].multiplier == Decimal("1")
    assert individual.amount_of("neustoyka") == Decimal("20000.00")
    assert legal_entity.amount_of("neustoyka") == Decimal("10000.00")


# --- Случай 6: объект не передан -------------------------------------------


def test_case6_object_not_transferred_counts_until_today(config):
    result = run(config, due_date=date(2025, 12, 1), actual_date=None, today=date(2025, 12, 31))

    assert result.period_end == date(2025, 12, 31)
    assert result.total_days == 30
    assert any("не передан" in note for note in result.notes)


# --- Случай 7: фактическая передача раньше срока по договору ---------------


def test_case7_transfer_before_due_date_gives_zero_without_negatives(config):
    result = run(config, due_date=date(2022, 2, 1), actual_date=date(2022, 1, 15))

    assert result.period_start is None
    assert result.total_days == 0
    assert result.segments == []
    assert result.total == Decimal("0.00")
    assert result.total >= 0
    assert any("Просрочка отсутствует" in note for note in result.notes)


def test_case7_transfer_exactly_on_due_date_gives_zero(config):
    result = run(config, due_date=date(2022, 2, 1), actual_date=date(2022, 2, 1))

    assert result.total_days == 0
    assert result.amount_of("neustoyka") == Decimal("0.00")


# --- Случай 8: високосный год и границы периода ----------------------------


def test_case8_leap_year_february_counted_correctly(config):
    result = run(config, due_date=date(2020, 2, 1), actual_date=date(2020, 3, 1))

    # 02.02–29.02 (28 дней) + 01.03 = 29 дней
    assert result.total_days == 29


def test_case8_non_leap_year_february_is_one_day_shorter(config):
    result = run(config, due_date=date(2021, 2, 1), actual_date=date(2021, 3, 1))

    assert result.total_days == 28


def test_case8_single_day_delay_counts_both_boundaries(config):
    """Правило по умолчанию: день передачи включается в просрочку."""
    result = run(config, due_date=date(2021, 1, 1), actual_date=date(2021, 1, 2))

    assert result.total_days == 1
    assert result.period_start == date(2021, 1, 2)
    assert result.period_end == date(2021, 1, 2)


def test_case8_exclusive_end_rule_drops_the_transfer_day(make_config):
    """Переключение правила подсчёта дней меняет результат ровно на день."""
    config = make_config(
        day_count_rule={
            "mode": "exclusive_end",
            "start_offset_days": 1,
            "basis": "тест: день передачи не считается",
            "requires_lawyer_review": False,
        }
    )
    single_day = calculate_delay(
        DelayInput(
            contract_price=PRICE,
            due_date=date(2021, 1, 1),
            actual_date=date(2021, 1, 2),
            today=date(2026, 1, 1),
        ),
        config,
    )
    assert single_day.total_days == 0

    longer = calculate_delay(
        DelayInput(
            contract_price=PRICE,
            due_date=date(2022, 1, 10),
            actual_date=date(2022, 2, 9),
            today=date(2026, 1, 1),
        ),
        config,
    )
    assert longer.total_days == 29  # на день меньше, чем в inclusive-режиме


def test_case8_moratorium_boundary_days_are_excluded_inclusively(config):
    """Первый и последний день моратория исключаются, соседние — считаются."""
    result = run(config, due_date=date(2022, 5, 30), actual_date=date(2022, 9, 2))

    starts = [(segment.start, segment.end) for segment in result.segments]
    assert starts == [
        (date(2022, 5, 31), date(2022, 5, 31)),
        (date(2022, 9, 1), date(2022, 9, 2)),
    ]


# --- Дополнительно: ограничение ставки, штраф, расходы, валидация -----------


def test_rate_cap_limits_the_applied_rate(make_config):
    config = make_config(
        rate_caps=[
            {
                "from": "2023-01-01",
                "to": "2023-12-31",
                "max_rate": 7.5,
                "basis": "тестовое ограничение ставки",
                "requires_lawyer_review": False,
            }
        ]
    )
    result = calculate_delay(
        DelayInput(
            contract_price=PRICE,
            due_date=date(2023, 2, 1),
            actual_date=date(2023, 3, 3),
            today=date(2026, 1, 1),
        ),
        config,
    )

    segment = result.segments[0]
    assert segment.rate == Decimal("7.5")
    assert segment.rate_before_cap == Decimal("20.0")
    assert segment.is_capped
    assert segment.cap_basis == "тестовое ограничение ставки"


def test_consumer_penalty_is_percent_of_neustoyka_and_moral_harm(make_config):
    config = make_config(
        consumer_penalty={
            "percent": 5,
            "base": "neustoyka_and_moral_harm",
            "basis": "ст. 10 214-ФЗ",
            "requires_lawyer_review": False,
        }
    )
    result = calculate_delay(
        DelayInput(
            contract_price=PRICE,
            due_date=date(2022, 1, 10),
            actual_date=date(2022, 2, 9),
            moral_harm=Decimal("50000"),
            today=date(2026, 1, 1),
        ),
        config,
    )

    assert result.amount_of("neustoyka") == Decimal("20000.00")
    assert result.amount_of("moral_harm") == Decimal("50000.00")
    # 5% от (20 000 + 50 000)
    assert result.amount_of("consumer_penalty") == Decimal("3500.00")
    assert result.total == Decimal("73500.00")


def test_expenses_are_added_as_separate_lines(config):
    result = run(
        config,
        due_date=date(2022, 1, 10),
        actual_date=date(2022, 2, 9),
        expenses=[
            ExpenseInput(title="Госпошлина", amount=Decimal("800"), code="duty"),
            ExpenseInput(title="Представитель", amount=Decimal("30000"), code="lawyer"),
            ExpenseInput(title="Пустая строка", amount=Decimal("0"), code="skip"),
        ],
    )

    codes = [line.code for line in result.lines]
    assert codes == ["neustoyka", "duty", "lawyer"]
    assert result.total == Decimal("50800.00")


def test_manual_rate_overrides_config(config):
    result = run(
        config,
        due_date=date(2022, 1, 10),
        actual_date=date(2022, 2, 9),
        rate_mode="manual",
        manual_rate=Decimal("21"),
    )

    assert result.segments[0].rate == Decimal("21")
    assert result.segments[0].amount == Decimal("42000.00")


def test_rate_mode_on_actual_date_uses_transfer_date_rate(config):
    result = run(
        config,
        due_date=date(2021, 12, 1),
        actual_date=date(2022, 1, 31),
        rate_mode="on_actual_date",
    )

    assert result.segments[0].rate == Decimal("10.0")  # ставка на 31.01.2022


def test_rate_mode_on_claim_date_requires_the_date(config):
    with pytest.raises(CalculationError, match="дату подачи"):
        run(
            config,
            due_date=date(2021, 12, 1),
            actual_date=date(2022, 1, 31),
            rate_mode="on_claim_date",
        )


def test_zero_price_is_rejected(config):
    with pytest.raises(CalculationError, match="больше нуля"):
        run(config, contract_price=Decimal("0"), due_date=date(2022, 1, 1))


def test_future_transfer_date_is_rejected(config):
    with pytest.raises(CalculationError, match="в будущем"):
        run(config, due_date=date(2025, 1, 1), actual_date=date(2026, 6, 1))


def test_unknown_rate_mode_is_rejected(config):
    with pytest.raises(CalculationError, match="Неизвестный режим"):
        run(config, due_date=date(2022, 1, 1), rate_mode="whatever")


def test_period_before_known_rates_reports_clear_error(config):
    from app.core.legal_config import LegalConfigError

    with pytest.raises(LegalConfigError, match="нет ключевой ставки"):
        run(config, due_date=date(2015, 1, 1), actual_date=date(2015, 3, 1))


def test_review_warnings_appear_for_unconfirmed_parameters(make_config):
    config = make_config(
        delay_penalty={
            "divisor": 300,
            "individual_multiplier": 2,
            "legal_entity_multiplier": 1,
            "basis": "ч. 2 ст. 6 214-ФЗ",
            "default_rate_mode": "on_obligation_date",
            "requires_lawyer_review": True,
        }
    )
    result = calculate_delay(
        DelayInput(
            contract_price=PRICE,
            due_date=date(2022, 1, 10),
            actual_date=date(2022, 2, 9),
            today=date(2026, 1, 1),
        ),
        config,
    )

    assert any("не подтверждён юристом" in warning for warning in result.warnings)


def test_segment_carries_basis_for_court_table(config):
    result = run(config, due_date=date(2022, 1, 10), actual_date=date(2022, 2, 9))
    segment = result.segments[0]

    assert segment.rate_source_date == date(2022, 1, 10)
    assert segment.divisor == Decimal("300")
    assert segment.base_amount == PRICE
    assert result.line("neustoyka").basis == "ч. 2 ст. 6 214-ФЗ"
