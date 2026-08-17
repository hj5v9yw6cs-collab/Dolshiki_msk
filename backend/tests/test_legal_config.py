import json
from datetime import date
from decimal import Decimal

import pytest

from app.core.legal_config import (
    DEFAULT_CONFIG_PATH,
    ConfigStore,
    LegalConfigError,
    load_config,
    parse_config,
)
from conftest import config_dict


def test_rate_on_returns_rate_effective_at_date(config):
    assert config.rate_on(date(2020, 6, 1)) == Decimal("6.0")
    assert config.rate_on(date(2022, 1, 1)) == Decimal("10.0")
    assert config.rate_on(date(2026, 1, 1)) == Decimal("20.0")


def test_rate_on_before_history_raises_actionable_error(config):
    with pytest.raises(LegalConfigError, match="Добавьте историческую ставку"):
        config.rate_on(date(2010, 1, 1))


def test_overlapping_moratoriums_are_rejected():
    with pytest.raises(LegalConfigError, match="пересекаются"):
        parse_config(
            config_dict(
                moratoriums=[
                    {"from": "2022-01-01", "to": "2022-06-30", "basis": "a"},
                    {"from": "2022-06-01", "to": "2022-12-31", "basis": "b"},
                ]
            )
        )


def test_overlapping_rate_caps_are_rejected():
    with pytest.raises(LegalConfigError, match="пересекаются"):
        parse_config(
            config_dict(
                rate_caps=[
                    {"from": "2022-01-01", "to": "2022-06-30", "max_rate": 7.5, "basis": "a"},
                    {"from": "2022-06-01", "to": "2022-12-31", "max_rate": 9.5, "basis": "b"},
                ]
            )
        )


def test_duplicate_rate_dates_are_rejected():
    with pytest.raises(LegalConfigError, match="две ставки на одну дату"):
        parse_config(
            config_dict(
                cbr_rates={
                    "items": [
                        {"from": "2022-01-01", "rate": 10.0},
                        {"from": "2022-01-01", "rate": 12.0},
                    ]
                }
            )
        )


def test_empty_rates_are_rejected():
    with pytest.raises(LegalConfigError, match="нечем считать"):
        parse_config(config_dict(cbr_rates={"items": []}))


def test_bad_date_is_rejected():
    with pytest.raises(LegalConfigError, match="некорректная дата"):
        parse_config(
            config_dict(moratoriums=[{"from": "31.12.2022", "to": "2023-01-01", "basis": "x"}])
        )


def test_unknown_day_count_mode_is_rejected():
    with pytest.raises(LegalConfigError, match="неизвестный режим"):
        parse_config(config_dict(day_count_rule={"mode": "as_the_judge_says"}))


def test_zero_divisor_is_rejected():
    with pytest.raises(LegalConfigError, match="больше нуля"):
        parse_config(config_dict(delay_penalty={"divisor": 0}))


def test_rates_are_sorted_regardless_of_input_order():
    parsed = parse_config(
        config_dict(
            cbr_rates={
                "items": [
                    {"from": "2023-01-01", "rate": 20.0},
                    {"from": "2020-01-01", "rate": 6.0},
                    {"from": "2022-01-01", "rate": 10.0},
                ]
            }
        )
    )
    assert [entry.from_date.year for entry in parsed.rates] == [2020, 2022, 2023]


def test_cap_for_returns_period_only_inside_its_range():
    parsed = parse_config(
        config_dict(
            rate_caps=[
                {"from": "2024-03-22", "to": "2025-06-30", "max_rate": 7.5, "basis": "ПП 326"}
            ]
        )
    )
    assert parsed.cap_for(date(2024, 5, 1)).max_rate == Decimal("7.5")
    assert parsed.cap_for(date(2026, 1, 1)) is None


def test_store_rejects_invalid_config_before_writing(tmp_path):
    path = tmp_path / "legal-config.json"
    path.write_text(json.dumps(config_dict()), encoding="utf-8")
    store = ConfigStore(path)
    original = path.read_text(encoding="utf-8")

    with pytest.raises(LegalConfigError):
        store.save(config_dict(cbr_rates={"items": []}), author="tester")

    assert path.read_text(encoding="utf-8") == original


def test_store_save_updates_author_and_reloads(tmp_path):
    path = tmp_path / "legal-config.json"
    path.write_text(json.dumps(config_dict()), encoding="utf-8")
    store = ConfigStore(path)

    data = config_dict()
    data["moratoriums"] = []
    updated = store.save(data, author="lawyer@example.com")

    assert updated.moratoriums == []
    assert updated.updated_by == "lawyer@example.com"
    assert store.get().moratoriums == []


def test_shipped_production_config_is_valid():
    """Боевой legal-config.json должен грузиться без ошибок."""
    parsed = load_config(DEFAULT_CONFIG_PATH)

    assert parsed.rates, "в конфиге должны быть ставки"
    assert parsed.moratoriums, "мораторные периоды должны быть заданы"
    assert parsed.disclaimer


def test_shipped_config_marks_legal_parameters_for_review():
    """Пока юрист не подтвердил параметры, расчёт обязан предупреждать."""
    parsed = load_config(DEFAULT_CONFIG_PATH)
    warnings = parsed.review_warnings(["day_count", "rates", "delay_penalty", "consumer_penalty"])

    assert len(warnings) == 4
