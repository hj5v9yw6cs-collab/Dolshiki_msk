"""Тесты режима 2 — недостатки отделки."""

from datetime import date
from decimal import Decimal

import pytest

from app.core.calculator import CalculationError, DefectsInput, calculate_defects

REPAIR = Decimal("300000")


def run(config, **kwargs):
    defaults = dict(repair_cost=REPAIR, today=date(2026, 1, 1))
    defaults.update(kwargs)
    return calculate_defects(DefectsInput(**defaults), config)


def test_delay_starts_after_response_period(config):
    """10 дней на удовлетворение требования + 1 день по правилу подсчёта."""
    result = run(
        config,
        demand_served_date=date(2022, 1, 1),
        satisfied_date=date(2022, 1, 21),
    )

    assert result.period_start == date(2022, 1, 12)
    assert result.period_end == date(2022, 1, 21)
    assert result.total_days == 10


def test_penalty_uses_repair_cost_and_its_own_divisor(config):
    result = run(
        config,
        demand_served_date=date(2022, 1, 1),
        satisfied_date=date(2022, 1, 21),
    )

    segment = result.segments[0]
    assert segment.base_amount == REPAIR
    assert segment.divisor == Decimal("150")
    assert segment.rate == Decimal("10.0")
    # 300 000 × 10 × 10% / 150 × 1
    assert segment.amount == Decimal("2000.00")
    assert result.amount_of("neustoyka") == Decimal("2000.00")


def test_repair_cost_and_expertise_are_separate_lines(config):
    result = run(
        config,
        demand_served_date=date(2022, 1, 1),
        satisfied_date=date(2022, 1, 21),
        expertise_cost=Decimal("45000"),
    )

    codes = [line.code for line in result.lines]
    assert codes == ["repair_cost", "neustoyka", "expertise"]
    assert result.amount_of("repair_cost") == Decimal("300000.00")
    assert result.amount_of("expertise") == Decimal("45000.00")
    assert result.total == Decimal("347000.00")


def test_penalty_is_capped_at_repair_cost(config):
    """Длинная просрочка не даёт неустойке превысить стоимость устранения."""
    result = run(
        config,
        demand_served_date=date(2023, 1, 1),
        satisfied_date=date(2025, 12, 31),
    )

    assert result.amount_of("neustoyka") == Decimal("300000.00")
    assert "Ограничена стоимостью" in result.line("neustoyka").note
    assert any("ограничена" in note.lower() for note in result.notes)


def test_cap_can_be_disabled_in_config(make_config):
    config = make_config(
        defects_penalty={
            "divisor": 150,
            "multiplier": 1,
            "response_period_days": 10,
            "cap_at_repair_cost": False,
            "apply_moratoriums": True,
            "basis": "ст. 7, ст. 10 214-ФЗ",
            "requires_lawyer_review": False,
        }
    )
    result = calculate_defects(
        DefectsInput(
            repair_cost=REPAIR,
            demand_served_date=date(2023, 1, 1),
            satisfied_date=date(2025, 12, 31),
            today=date(2026, 1, 1),
        ),
        config,
    )

    assert result.amount_of("neustoyka") > Decimal("300000.00")


def test_moratorium_excluded_when_enabled(config):
    result = run(
        config,
        demand_served_date=date(2022, 5, 1),
        satisfied_date=date(2022, 9, 30),
    )

    assert len(result.excluded) == 1
    assert result.excluded[0].days == 92
    assert len(result.segments) == 2


def test_moratorium_ignored_when_disabled_in_config(make_config):
    config = make_config(
        defects_penalty={
            "divisor": 150,
            "multiplier": 1,
            "response_period_days": 10,
            "cap_at_repair_cost": False,
            "apply_moratoriums": False,
            "basis": "ст. 7, ст. 10 214-ФЗ",
            "requires_lawyer_review": False,
        }
    )
    result = calculate_defects(
        DefectsInput(
            repair_cost=REPAIR,
            demand_served_date=date(2022, 5, 1),
            satisfied_date=date(2022, 9, 30),
            today=date(2026, 1, 1),
        ),
        config,
    )

    assert result.excluded == []
    assert len(result.segments) == 1


def test_demand_not_satisfied_counts_until_today(config):
    result = run(
        config,
        demand_served_date=date(2025, 11, 1),
        satisfied_date=None,
        today=date(2025, 12, 31),
    )

    assert result.period_end == date(2025, 12, 31)
    assert any("не удовлетворено" in note for note in result.notes)


def test_satisfied_within_response_period_gives_no_penalty(config):
    result = run(
        config,
        demand_served_date=date(2022, 1, 1),
        satisfied_date=date(2022, 1, 5),
        expertise_cost=Decimal("45000"),
    )

    assert result.segments == []
    assert result.amount_of("neustoyka") == Decimal("0.00")
    # Стоимость устранения и экспертиза всё равно взыскиваются
    assert result.total == Decimal("345000.00")


def test_consumer_penalty_can_include_repair_cost_in_base(make_config):
    config = make_config(
        consumer_penalty={
            "percent": 5,
            "base": "claim_and_neustoyka_and_moral_harm",
            "basis": "ст. 10 214-ФЗ",
            "requires_lawyer_review": False,
        }
    )
    result = calculate_defects(
        DefectsInput(
            repair_cost=REPAIR,
            demand_served_date=date(2022, 1, 1),
            satisfied_date=date(2022, 1, 21),
            moral_harm=Decimal("20000"),
            today=date(2026, 1, 1),
        ),
        config,
    )

    # 5% от (300 000 + 2 000 + 20 000)
    assert result.amount_of("consumer_penalty") == Decimal("16100.00")


def test_repair_cost_can_be_excluded_from_total(config):
    result = run(
        config,
        demand_served_date=date(2022, 1, 1),
        satisfied_date=date(2022, 1, 21),
        include_repair_cost_in_total=False,
    )

    assert result.line("repair_cost") is None
    assert result.total == Decimal("2000.00")


def test_zero_repair_cost_is_rejected(config):
    with pytest.raises(CalculationError, match="больше нуля"):
        run(config, repair_cost=Decimal("0"), demand_served_date=date(2022, 1, 1))


def test_future_satisfaction_date_is_rejected(config):
    with pytest.raises(CalculationError, match="в будущем"):
        run(
            config,
            demand_served_date=date(2025, 1, 1),
            satisfied_date=date(2026, 6, 1),
        )
