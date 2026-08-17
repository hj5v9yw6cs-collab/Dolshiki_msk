"""Загрузка и валидация юридического конфига.

Принцип: ни одна ставка, мораторный период или размер штрафа не зашиты
в коде расчёта. Всё приходит отсюда, у каждого параметра есть основание
(номер закона/постановления) и флаг requires_lawyer_review. Пока флаг
не снят, расчёт выполняется, но возвращает предупреждение — чтобы цифра
в суде не оказалась взятой из воздуха.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from .periods import DateRange

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "legal-config.json"


class LegalConfigError(Exception):
    """Конфиг невалиден — расчёт выполнять нельзя."""


def _parse_date(value: str, where: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise LegalConfigError(f"{where}: некорректная дата {value!r}") from exc


def _parse_decimal(value: Any, where: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:
        raise LegalConfigError(f"{where}: некорректное число {value!r}") from exc


@dataclass(frozen=True)
class RateEntry:
    from_date: date
    rate: Decimal


@dataclass(frozen=True)
class NamedPeriod:
    """Мораторий или ограничение ставки — период с правовым основанием."""

    period: DateRange
    basis: str
    note: str = ""
    max_rate: Optional[Decimal] = None
    requires_lawyer_review: bool = True


@dataclass(frozen=True)
class DayCountRule:
    mode: str
    start_offset_days: int
    basis: str
    note: str = ""
    requires_lawyer_review: bool = True


@dataclass(frozen=True)
class DelayPenaltyRule:
    divisor: Decimal
    individual_multiplier: Decimal
    legal_entity_multiplier: Decimal
    basis: str
    default_rate_mode: str
    requires_lawyer_review: bool = True


@dataclass(frozen=True)
class DefectsPenaltyRule:
    divisor: Decimal
    multiplier: Decimal
    response_period_days: int
    cap_at_repair_cost: bool
    apply_moratoriums: bool
    basis: str
    note: str = ""
    requires_lawyer_review: bool = True


@dataclass(frozen=True)
class ConsumerPenaltyRule:
    percent: Decimal
    base: str
    basis: str
    note: str = ""
    requires_lawyer_review: bool = True


@dataclass(frozen=True)
class LegalConfig:
    version: int
    updated_at: str
    updated_by: str
    day_count: DayCountRule
    rates: List[RateEntry]
    rates_source: str
    rates_requires_review: bool
    rates_auto_sync: bool
    moratoriums: List[NamedPeriod]
    rate_caps: List[NamedPeriod]
    delay_penalty: DelayPenaltyRule
    defects_penalty: DefectsPenaltyRule
    consumer_penalty: ConsumerPenaltyRule
    disclaimer: str
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    # --- ставки ---------------------------------------------------------

    def rate_on(self, day: date) -> Decimal:
        """Ключевая ставка, действующая на указанную дату."""
        applicable = None
        for entry in self.rates:
            if entry.from_date <= day:
                applicable = entry
            else:
                break
        if applicable is None:
            raise LegalConfigError(
                f"В конфиге нет ключевой ставки на {day.isoformat()}: "
                f"самая ранняя запись — {self.rates[0].from_date.isoformat()}. "
                "Добавьте историческую ставку в legal-config.json."
            )
        return applicable.rate

    def rate_change_dates(self) -> List[date]:
        return [entry.from_date for entry in self.rates]

    def latest_rate(self) -> RateEntry:
        return self.rates[-1]

    # --- периоды --------------------------------------------------------

    def moratorium_ranges(self) -> List[DateRange]:
        return [m.period for m in self.moratoriums]

    def cap_for(self, day: date) -> Optional[NamedPeriod]:
        """Ограничение ставки, действующее на дату определения ставки."""
        for cap in self.rate_caps:
            if cap.period.contains(day) and cap.max_rate is not None:
                return cap
        return None

    def moratoriums_touching(self, period: DateRange) -> List[NamedPeriod]:
        return [m for m in self.moratoriums if m.period.overlaps(period)]

    # --- предупреждения -------------------------------------------------

    def review_warnings(self, used: List[str]) -> List[str]:
        """Тексты предупреждений по непроверенным параметрам."""
        checks = {
            "day_count": (self.day_count.requires_lawyer_review, "правило подсчёта дней просрочки"),
            "rates": (self.rates_requires_review, "история ключевой ставки ЦБ"),
            "delay_penalty": (self.delay_penalty.requires_lawyer_review, "формула неустойки за просрочку передачи"),
            "defects_penalty": (self.defects_penalty.requires_lawyer_review, "формула неустойки по недостаткам"),
            "consumer_penalty": (self.consumer_penalty.requires_lawyer_review, "размер штрафа в пользу потребителя"),
        }
        warnings: List[str] = []
        for key in used:
            flagged, title = checks.get(key, (False, ""))
            if flagged:
                warnings.append(f"Параметр «{title}» не подтверждён юристом (requires_lawyer_review).")
        return warnings


def _named_periods(items: List[Dict[str, Any]], where: str) -> List[NamedPeriod]:
    result: List[NamedPeriod] = []
    for index, item in enumerate(items):
        location = f"{where}[{index}]"
        period = DateRange(
            _parse_date(item["from"], location),
            _parse_date(item["to"], location),
        )
        max_rate = item.get("max_rate")
        result.append(
            NamedPeriod(
                period=period,
                basis=item.get("basis", ""),
                note=item.get("note", ""),
                max_rate=_parse_decimal(max_rate, location) if max_rate is not None else None,
                requires_lawyer_review=bool(item.get("requires_lawyer_review", True)),
            )
        )
    return sorted(result, key=lambda p: p.period.start)


def _validate_no_overlap(periods: List[NamedPeriod], where: str) -> None:
    for earlier, later in zip(periods, periods[1:]):
        if earlier.period.overlaps(later.period):
            raise LegalConfigError(
                f"{where}: периоды пересекаются — "
                f"{earlier.period.start}..{earlier.period.end} и "
                f"{later.period.start}..{later.period.end}. "
                "Пересечение делает расчёт неоднозначным."
            )


def parse_config(data: Dict[str, Any]) -> LegalConfig:
    rates_block = data.get("cbr_rates") or {}
    rate_items = rates_block.get("items") or []
    if not rate_items:
        raise LegalConfigError("cbr_rates.items пуст — нечем считать неустойку.")

    rates = sorted(
        (
            RateEntry(_parse_date(item["from"], "cbr_rates"), _parse_decimal(item["rate"], "cbr_rates"))
            for item in rate_items
        ),
        key=lambda entry: entry.from_date,
    )
    for earlier, later in zip(rates, rates[1:]):
        if earlier.from_date == later.from_date:
            raise LegalConfigError(f"cbr_rates: две ставки на одну дату {earlier.from_date}.")

    moratoriums = _named_periods(data.get("moratoriums") or [], "moratoriums")
    _validate_no_overlap(moratoriums, "moratoriums")
    rate_caps = _named_periods(data.get("rate_caps") or [], "rate_caps")
    _validate_no_overlap(rate_caps, "rate_caps")

    day_block = data.get("day_count_rule") or {}
    mode = day_block.get("mode", "inclusive_both_ends")
    if mode not in ("inclusive_both_ends", "exclusive_end"):
        raise LegalConfigError(f"day_count_rule.mode: неизвестный режим {mode!r}")

    delay_block = data.get("delay_penalty") or {}
    defects_block = data.get("defects_penalty") or {}
    penalty_block = data.get("consumer_penalty") or {}

    divisor = _parse_decimal(delay_block.get("divisor", 300), "delay_penalty.divisor")
    if divisor <= 0:
        raise LegalConfigError("delay_penalty.divisor должен быть больше нуля.")

    return LegalConfig(
        version=int(data.get("version", 0)),
        updated_at=str(data.get("updated_at", "")),
        updated_by=str(data.get("updated_by", "")),
        day_count=DayCountRule(
            mode=mode,
            start_offset_days=int(day_block.get("start_offset_days", 1)),
            basis=day_block.get("basis", ""),
            note=day_block.get("note", ""),
            requires_lawyer_review=bool(day_block.get("requires_lawyer_review", True)),
        ),
        rates=rates,
        rates_source=str(rates_block.get("source", "")),
        rates_requires_review=bool(rates_block.get("requires_lawyer_review", True)),
        rates_auto_sync=bool(rates_block.get("auto_sync", True)),
        moratoriums=moratoriums,
        rate_caps=rate_caps,
        delay_penalty=DelayPenaltyRule(
            divisor=divisor,
            individual_multiplier=_parse_decimal(delay_block.get("individual_multiplier", 2), "delay_penalty"),
            legal_entity_multiplier=_parse_decimal(delay_block.get("legal_entity_multiplier", 1), "delay_penalty"),
            basis=delay_block.get("basis", ""),
            default_rate_mode=delay_block.get("default_rate_mode", "on_obligation_date"),
            requires_lawyer_review=bool(delay_block.get("requires_lawyer_review", True)),
        ),
        defects_penalty=DefectsPenaltyRule(
            divisor=_parse_decimal(defects_block.get("divisor", 150), "defects_penalty"),
            multiplier=_parse_decimal(defects_block.get("multiplier", 1), "defects_penalty"),
            response_period_days=int(defects_block.get("response_period_days", 10)),
            cap_at_repair_cost=bool(defects_block.get("cap_at_repair_cost", True)),
            apply_moratoriums=bool(defects_block.get("apply_moratoriums", True)),
            basis=defects_block.get("basis", ""),
            note=defects_block.get("note", ""),
            requires_lawyer_review=bool(defects_block.get("requires_lawyer_review", True)),
        ),
        consumer_penalty=ConsumerPenaltyRule(
            percent=_parse_decimal(penalty_block.get("percent", 0), "consumer_penalty"),
            base=penalty_block.get("base", "neustoyka_and_moral_harm"),
            basis=penalty_block.get("basis", ""),
            note=penalty_block.get("note", ""),
            requires_lawyer_review=bool(penalty_block.get("requires_lawyer_review", True)),
        ),
        disclaimer=str(data.get("disclaimer", "")),
        raw=data,
    )


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> LegalConfig:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LegalConfigError(f"Не найден юридический конфиг: {path}") from exc
    except json.JSONDecodeError as exc:
        raise LegalConfigError(f"Юридический конфиг повреждён ({path}): {exc}") from exc
    return parse_config(data)


class ConfigStore:
    """Кеш конфига в памяти с горячей перезагрузкой после правки в админке."""

    def __init__(self, path: Path | str = DEFAULT_CONFIG_PATH) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._config: Optional[LegalConfig] = None

    def get(self) -> LegalConfig:
        with self._lock:
            if self._config is None:
                self._config = load_config(self.path)
            return self._config

    def reload(self) -> LegalConfig:
        with self._lock:
            self._config = load_config(self.path)
            return self._config

    def save(self, data: Dict[str, Any], author: str) -> LegalConfig:
        """Записывает новый конфиг, предварительно его провалидировав."""
        parse_config(data)  # падаем до записи, а не после
        data = dict(data)
        data["updated_by"] = author
        with self._lock:
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            self._config = load_config(self.path)
            return self._config


store = ConfigStore()
