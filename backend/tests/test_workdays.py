"""Перенос срока с нерабочего дня — статья 193 ГК РФ."""

from datetime import date
from decimal import Decimal

import pytest

from app.core.calculator import DelayInput, calculate_delay
from app.core.legal_config import parse_config
from app.core.workdays import parse_workdays
from conftest import config_dict

WORKDAYS = {
    "apply_article_193": True,
    "basis": "ст. 193 ГК РФ",
    "weekend_weekdays": [5, 6],
    "holidays_every_year": ["01-01", "01-02", "01-03", "01-04", "01-05",
                            "01-06", "01-07", "01-08", "02-23", "03-08",
                            "05-01", "05-09", "06-12", "11-04"],
    "extra_non_working": [],
    "working_exceptions": [],
    "requires_lawyer_review": False,
}


def rule(**overrides):
    return parse_workdays({"working_days": {**WORKDAYS, **overrides}})


# --- сам календарь ---------------------------------------------------------


def test_weekend_is_non_working():
    calendar = rule()

    assert calendar.is_non_working(date(2024, 11, 30))  # суббота
    assert calendar.is_non_working(date(2024, 12, 1))   # воскресенье
    assert not calendar.is_non_working(date(2024, 12, 2))


def test_fixed_holidays_are_non_working_every_year():
    calendar = rule()

    for year in (2024, 2025, 2026):
        assert calendar.is_non_working(date(year, 1, 3))
        assert calendar.is_non_working(date(year, 5, 9))
        assert calendar.is_non_working(date(year, 11, 4))


def test_saturday_shifts_to_monday():
    assert rule().next_working_day(date(2024, 11, 30)) == date(2024, 12, 2)


def test_new_year_holidays_shift_past_the_whole_block():
    # 1–8 января нерабочие; 9 января 2025 — четверг.
    assert rule().next_working_day(date(2025, 1, 1)) == date(2025, 1, 9)


def test_working_day_is_not_moved():
    assert rule().next_working_day(date(2024, 12, 2)) == date(2024, 12, 2)


def test_extra_non_working_day_is_respected():
    calendar = rule(extra_non_working=["2026-05-08"])

    assert calendar.is_non_working(date(2026, 5, 8))


def test_working_exception_beats_the_weekend():
    """Рабочая суббота из производственного календаря."""
    calendar = rule(working_exceptions=["2026-11-07"])

    assert not calendar.is_non_working(date(2026, 11, 7))


def test_rule_can_be_switched_off():
    calendar = rule(apply_article_193=False)

    assert calendar.next_working_day(date(2024, 11, 30)) == date(2024, 11, 30)


def test_broken_date_in_config_is_reported():
    with pytest.raises(ValueError, match="некорректная дата"):
        rule(extra_non_working=["не дата"])


# --- влияние на расчёт -----------------------------------------------------


def config_with_workdays(**overrides):
    return parse_config(config_dict(working_days={**WORKDAYS, **overrides}))


def calc(config, due, actual):
    return calculate_delay(
        DelayInput(contract_price=Decimal("1000000"), due_date=due,
                   actual_date=actual, today=date(2026, 8, 18)),
        config,
    )


def test_deadline_on_saturday_starts_the_delay_later():
    """Срок 30.11.2024 — суббота: просрочка идёт не с 01.12, а с 03.12."""
    result = calc(config_with_workdays(), date(2024, 11, 30), date(2024, 12, 10))

    assert result.period_start == date(2024, 12, 3)
    assert any("выпал на нерабочий день" in note for note in result.notes)


def test_shift_reduces_the_amount():
    """Перенос обязан уменьшать сумму — иначе он бессмысленен."""
    with_rule = calc(config_with_workdays(), date(2024, 11, 30), date(2024, 12, 10))
    without = calc(config_with_workdays(apply_article_193=False), date(2024, 11, 30), date(2024, 12, 10))

    assert with_rule.total_days == without.total_days - 2
    assert with_rule.amount_of("neustoyka") < without.amount_of("neustoyka")


def test_no_note_when_the_deadline_is_a_working_day():
    """Примечание не должно появляться на каждом расчёте без повода."""
    result = calc(config_with_workdays(), date(2024, 12, 2), date(2024, 12, 10))

    assert result.period_start == date(2024, 12, 3)
    assert not any("нерабочий день" in note for note in result.notes)


def test_shift_can_remove_the_delay_entirely():
    """Передали в понедельник, срок был в субботу — просрочки нет."""
    result = calc(config_with_workdays(), date(2024, 11, 30), date(2024, 12, 2))

    assert result.total_days == 0
    assert result.amount_of("neustoyka") == Decimal("0.00")


def test_defects_deadline_also_shifts(api_client):
    from app.core.calculator import DefectsInput, calculate_defects

    # Требование вручено 21.11.2024 + 10 дней = 01.12.2024, воскресенье.
    result = calculate_defects(
        DefectsInput(repair_cost=Decimal("300000"), demand_served_date=date(2024, 11, 21),
                     satisfied_date=date(2024, 12, 20), today=date(2026, 8, 18)),
        config_with_workdays(),
    )

    assert result.period_start == date(2024, 12, 3)
    assert any("выпал на нерабочий день" in note for note in result.notes)


def test_unconfirmed_calendar_warns():
    result = calc(config_with_workdays(requires_lawyer_review=True), date(2024, 11, 30), date(2024, 12, 10))

    assert any("ст. 193" in warning for warning in result.warnings)
