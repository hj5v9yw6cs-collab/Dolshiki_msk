"""Расчётное ядро.

Два режима:
  * delay   — неустойка за просрочку передачи объекта (ч. 2 ст. 6 214-ФЗ);
  * defects — стоимость устранения недостатков и неустойка за просрочку
              удовлетворения требования (ст. 7, ст. 10 214-ФЗ).

Общая механика одинакова:
  1) построить период просрочки;
  2) вычесть мораторные периоды;
  3) при необходимости разрезать остаток по датам изменения ставки;
  4) посчитать каждый сегмент, применив ограничение ставки;
  5) добавить моральный вред, штраф и расходы отдельными строками.

Ни одна юридическая константа здесь не зашита — всё приходит из LegalConfig.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

from ..legal_config import LegalConfig, LegalConfigError
from ..money import money, percent_of, round_kopecks
from ..periods import DateRange, make_range, split_at, subtract
from .models import (
    RATE_MODE_TITLES,
    RATE_MODES,
    CalculationResult,
    ExcludedPeriod,
    LineItem,
    Segment,
)

ZERO = Decimal("0.00")


class CalculationError(Exception):
    """Некорректный ввод — расчёт невозможен."""


@dataclass
class ExpenseInput:
    title: str
    amount: Decimal
    code: str = "expense"


@dataclass
class DelayInput:
    """Режим 1: просрочка передачи объекта."""

    contract_price: Decimal
    due_date: date                       # срок передачи по договору
    actual_date: Optional[date] = None   # фактическая передача; None — не передан
    is_individual: bool = True
    rate_mode: str = ""                  # пусто -> default_rate_mode из конфига
    manual_rate: Optional[Decimal] = None
    claim_date: Optional[date] = None    # для режима on_claim_date
    moral_harm: Decimal = ZERO
    include_consumer_penalty: bool = True
    expenses: List[ExpenseInput] = None
    today: Optional[date] = None         # для тестов и фиксации даты расчёта


@dataclass
class DefectsInput:
    """Режим 2: недостатки отделки."""

    repair_cost: Decimal                    # стоимость устранения по заключению
    demand_served_date: date                # дата вручения требования застройщику
    satisfied_date: Optional[date] = None   # дата удовлетворения; None — не удовлетворено
    expertise_cost: Decimal = ZERO
    rate_mode: str = ""
    manual_rate: Optional[Decimal] = None
    claim_date: Optional[date] = None
    moral_harm: Decimal = ZERO
    include_consumer_penalty: bool = True
    include_repair_cost_in_total: bool = True
    expenses: List[ExpenseInput] = None
    today: Optional[date] = None


# ---------------------------------------------------------------------------
# Общие помощники
# ---------------------------------------------------------------------------


def _today(explicit: Optional[date]) -> date:
    return explicit or date.today()


def _resolve_rate_mode(requested: str, config: LegalConfig) -> str:
    mode = requested or config.delay_penalty.default_rate_mode
    if mode not in RATE_MODES:
        raise CalculationError(
            f"Неизвестный режим определения ставки: {mode!r}. "
            f"Допустимые: {', '.join(RATE_MODES)}"
        )
    return mode


def _rate_determination_date(
    mode: str,
    *,
    obligation_date: date,
    actual_date: date,
    claim_date: Optional[date],
    segment_start: date,
) -> date:
    if mode == "on_obligation_date":
        return obligation_date
    if mode == "on_actual_date":
        return actual_date
    if mode == "on_claim_date":
        if claim_date is None:
            raise CalculationError(
                "Для режима «ставка на дату подачи иска» нужно указать дату подачи."
            )
        return claim_date
    if mode == "per_segment":
        return segment_start
    return obligation_date  # manual — дата нужна только для проверки ограничения


def _delay_period(
    *,
    start_from: date,
    end_raw: date,
    config: LegalConfig,
) -> Optional[DateRange]:
    """Период просрочки с учётом правила подсчёта дней из конфига."""
    start = start_from + timedelta(days=config.day_count.start_offset_days)
    end = end_raw
    if config.day_count.mode == "exclusive_end":
        end = end_raw - timedelta(days=1)
    return make_range(start, end)


def _excluded_periods(period: DateRange, config: LegalConfig) -> List[ExcludedPeriod]:
    excluded: List[ExcludedPeriod] = []
    for moratorium in config.moratoriums_touching(period):
        overlap = make_range(
            max(period.start, moratorium.period.start),
            min(period.end, moratorium.period.end),
        )
        if overlap:
            excluded.append(
                ExcludedPeriod(
                    start=overlap.start,
                    end=overlap.end,
                    days=overlap.days,
                    basis=moratorium.basis,
                    note=moratorium.note,
                )
            )
    return excluded


def _build_segments(
    period: DateRange,
    config: LegalConfig,
    *,
    apply_moratoriums: bool,
    rate_mode: str,
) -> List[DateRange]:
    pieces = (
        subtract(period, config.moratorium_ranges()) if apply_moratoriums else [period]
    )
    if rate_mode != "per_segment":
        return pieces

    result: List[DateRange] = []
    boundaries = config.rate_change_dates()
    for piece in pieces:
        result.extend(split_at(piece, boundaries))
    return result


def _effective_rate(
    config: LegalConfig,
    determination_date: date,
    manual_rate: Optional[Decimal],
    rate_mode: str,
) -> tuple[Decimal, Optional[Decimal], Optional[str]]:
    """Возвращает (ставка, ставка_до_ограничения, основание_ограничения)."""
    if rate_mode == "manual":
        if manual_rate is None:
            raise CalculationError("Выбран ручной ввод ставки, но ставка не передана.")
        base_rate = money(manual_rate)
    else:
        base_rate = config.rate_on(determination_date)

    cap = config.cap_for(determination_date)
    if cap and cap.max_rate is not None and base_rate > cap.max_rate:
        return cap.max_rate, base_rate, cap.basis
    return base_rate, None, None


def _consumer_penalty_base(
    config: LegalConfig,
    *,
    neustoyka: Decimal,
    moral_harm: Decimal,
    claim_amount: Decimal,
) -> Decimal:
    base = config.consumer_penalty.base
    if base == "neustoyka_only":
        return neustoyka
    if base == "claim_and_neustoyka_and_moral_harm":
        return neustoyka + moral_harm + claim_amount
    return neustoyka + moral_harm  # neustoyka_and_moral_harm — значение по умолчанию


def _expense_lines(expenses: Optional[List[ExpenseInput]]) -> List[LineItem]:
    lines: List[LineItem] = []
    for expense in expenses or []:
        amount = round_kopecks(money(expense.amount))
        if amount <= 0:
            continue
        lines.append(
            LineItem(code=expense.code, title=expense.title, amount=amount, basis="судебные расходы")
        )
    return lines


def _assemble_extras(
    config: LegalConfig,
    *,
    neustoyka: Decimal,
    moral_harm: Decimal,
    claim_amount: Decimal,
    include_penalty: bool,
    expenses: Optional[List[ExpenseInput]],
) -> tuple[List[LineItem], List[str]]:
    lines: List[LineItem] = []
    used: List[str] = []

    moral_harm = round_kopecks(money(moral_harm))
    if moral_harm > 0:
        lines.append(
            LineItem(
                code="moral_harm",
                title="Компенсация морального вреда",
                amount=moral_harm,
                basis="ст. 15 Закона РФ «О защите прав потребителей»",
                note="Размер определяется судом; указан заявляемый.",
            )
        )

    if include_penalty and config.consumer_penalty.percent > 0:
        base = _consumer_penalty_base(
            config,
            neustoyka=neustoyka,
            moral_harm=moral_harm,
            claim_amount=claim_amount,
        )
        amount = round_kopecks(percent_of(base, config.consumer_penalty.percent))
        if amount > 0:
            lines.append(
                LineItem(
                    code="consumer_penalty",
                    title=f"Штраф {config.consumer_penalty.percent}% в пользу потребителя",
                    amount=amount,
                    basis=config.consumer_penalty.basis,
                    note=config.consumer_penalty.note,
                )
            )
            used.append("consumer_penalty")

    lines.extend(_expense_lines(expenses))
    return lines, used


# ---------------------------------------------------------------------------
# Режим 1 — просрочка передачи объекта
# ---------------------------------------------------------------------------


def calculate_delay(data: DelayInput, config: LegalConfig) -> CalculationResult:
    price = money(data.contract_price)
    if price <= 0:
        raise CalculationError("Цена договора должна быть больше нуля.")

    today = _today(data.today)
    if data.actual_date and data.actual_date > today:
        raise CalculationError("Дата фактической передачи не может быть в будущем.")

    rate_mode = _resolve_rate_mode(data.rate_mode, config)
    end_raw = data.actual_date or today
    period = _delay_period(start_from=data.due_date, end_raw=end_raw, config=config)

    multiplier = (
        config.delay_penalty.individual_multiplier
        if data.is_individual
        else config.delay_penalty.legal_entity_multiplier
    )
    divisor = config.delay_penalty.divisor
    used_params = ["day_count", "rates", "delay_penalty"]

    if period is None:
        # Просрочки нет: объект передан в срок или раньше.
        lines, extra_used = _assemble_extras(
            config,
            neustoyka=ZERO,
            moral_harm=data.moral_harm,
            claim_amount=ZERO,
            include_penalty=data.include_consumer_penalty,
            expenses=data.expenses,
        )
        total = round_kopecks(sum((line.amount for line in lines), ZERO))
        return CalculationResult(
            mode="delay",
            period_start=None,
            period_end=None,
            total_days=0,
            segments=[],
            excluded=[],
            lines=lines,
            total=total,
            rate_mode=rate_mode,
            rate_mode_title=RATE_MODE_TITLES[rate_mode],
            warnings=config.review_warnings(used_params + extra_used),
            notes=["Просрочка отсутствует: объект передан в срок или ранее срока по договору."],
            disclaimer=config.disclaimer,
            config_version=config.version,
        )

    excluded = _excluded_periods(period, config)
    ranges = _build_segments(period, config, apply_moratoriums=True, rate_mode=rate_mode)

    segments: List[Segment] = []
    for piece in ranges:
        determination_date = _rate_determination_date(
            rate_mode,
            obligation_date=data.due_date,
            actual_date=end_raw,
            claim_date=data.claim_date,
            segment_start=piece.start,
        )
        rate, before_cap, cap_basis = _effective_rate(
            config, determination_date, data.manual_rate, rate_mode
        )
        amount = price * Decimal(piece.days) * (rate / Decimal(100)) / divisor * multiplier
        segments.append(
            Segment(
                start=piece.start,
                end=piece.end,
                days=piece.days,
                rate=rate,
                rate_source_date=determination_date,
                multiplier=multiplier,
                divisor=divisor,
                base_amount=price,
                amount=round_kopecks(amount),
                rate_before_cap=before_cap,
                cap_basis=cap_basis,
            )
        )

    neustoyka = round_kopecks(sum((segment.amount for segment in segments), ZERO))
    lines: List[LineItem] = [
        LineItem(
            code="neustoyka",
            title="Неустойка за нарушение срока передачи объекта",
            amount=neustoyka,
            basis=config.delay_penalty.basis,
        )
    ]
    extras, extra_used = _assemble_extras(
        config,
        neustoyka=neustoyka,
        moral_harm=data.moral_harm,
        claim_amount=ZERO,
        include_penalty=data.include_consumer_penalty,
        expenses=data.expenses,
    )
    lines.extend(extras)
    total = round_kopecks(sum((line.amount for line in lines), ZERO))

    notes: List[str] = []
    if data.actual_date is None:
        notes.append(f"Объект не передан: расчёт выполнен по {today.strftime('%d.%m.%Y')}.")
    if excluded:
        notes.append(
            "Из расчёта исключены мораторные периоды — см. отдельную таблицу с основаниями."
        )

    return CalculationResult(
        mode="delay",
        period_start=period.start,
        period_end=period.end,
        total_days=sum(segment.days for segment in segments),
        segments=segments,
        excluded=excluded,
        lines=lines,
        total=total,
        rate_mode=rate_mode,
        rate_mode_title=RATE_MODE_TITLES[rate_mode],
        warnings=config.review_warnings(used_params + extra_used),
        notes=notes,
        disclaimer=config.disclaimer,
        config_version=config.version,
    )


# ---------------------------------------------------------------------------
# Режим 2 — недостатки отделки
# ---------------------------------------------------------------------------


def calculate_defects(data: DefectsInput, config: LegalConfig) -> CalculationResult:
    repair_cost = money(data.repair_cost)
    if repair_cost <= 0:
        raise CalculationError("Стоимость устранения недостатков должна быть больше нуля.")

    today = _today(data.today)
    if data.satisfied_date and data.satisfied_date > today:
        raise CalculationError("Дата удовлетворения требования не может быть в будущем.")

    rules = config.defects_penalty
    rate_mode = _resolve_rate_mode(data.rate_mode, config)
    deadline = data.demand_served_date + timedelta(days=rules.response_period_days)
    end_raw = data.satisfied_date or today
    period = _delay_period(start_from=deadline, end_raw=end_raw, config=config)

    used_params = ["day_count", "rates", "defects_penalty"]
    excluded: List[ExcludedPeriod] = []
    segments: List[Segment] = []
    neustoyka = ZERO
    capped = False

    if period is not None:
        if rules.apply_moratoriums:
            excluded = _excluded_periods(period, config)
        ranges = _build_segments(
            period, config, apply_moratoriums=rules.apply_moratoriums, rate_mode=rate_mode
        )
        for piece in ranges:
            determination_date = _rate_determination_date(
                rate_mode,
                obligation_date=deadline,
                actual_date=end_raw,
                claim_date=data.claim_date,
                segment_start=piece.start,
            )
            rate, before_cap, cap_basis = _effective_rate(
                config, determination_date, data.manual_rate, rate_mode
            )
            amount = (
                repair_cost
                * Decimal(piece.days)
                * (rate / Decimal(100))
                / rules.divisor
                * rules.multiplier
            )
            segments.append(
                Segment(
                    start=piece.start,
                    end=piece.end,
                    days=piece.days,
                    rate=rate,
                    rate_source_date=determination_date,
                    multiplier=rules.multiplier,
                    divisor=rules.divisor,
                    base_amount=repair_cost,
                    amount=round_kopecks(amount),
                    rate_before_cap=before_cap,
                    cap_basis=cap_basis,
                )
            )
        neustoyka = round_kopecks(sum((segment.amount for segment in segments), ZERO))
        if rules.cap_at_repair_cost and neustoyka > repair_cost:
            neustoyka = round_kopecks(repair_cost)
            capped = True

    lines: List[LineItem] = []
    claim_amount = ZERO
    if data.include_repair_cost_in_total:
        claim_amount = round_kopecks(repair_cost)
        lines.append(
            LineItem(
                code="repair_cost",
                title="Стоимость устранения недостатков",
                amount=claim_amount,
                basis="ст. 7 214-ФЗ, заключение эксперта",
            )
        )

    lines.append(
        LineItem(
            code="neustoyka",
            title="Неустойка за просрочку удовлетворения требования",
            amount=neustoyka,
            basis=rules.basis,
            note="Ограничена стоимостью устранения недостатков." if capped else "",
        )
    )

    expertise = round_kopecks(money(data.expertise_cost))
    if expertise > 0:
        lines.append(
            LineItem(
                code="expertise",
                title="Расходы на досудебную экспертизу",
                amount=expertise,
                basis="судебные издержки",
            )
        )

    extras, extra_used = _assemble_extras(
        config,
        neustoyka=neustoyka,
        moral_harm=data.moral_harm,
        claim_amount=claim_amount,
        include_penalty=data.include_consumer_penalty,
        expenses=data.expenses,
    )
    lines.extend(extras)
    total = round_kopecks(sum((line.amount for line in lines), ZERO))

    notes: List[str] = []
    if data.satisfied_date is None:
        notes.append(f"Требование не удовлетворено: расчёт выполнен по {today.strftime('%d.%m.%Y')}.")
    notes.append(
        f"Срок на удовлетворение требования — {rules.response_period_days} дн., "
        f"просрочка исчисляется с {(deadline + timedelta(days=config.day_count.start_offset_days)).strftime('%d.%m.%Y')}."
    )
    if capped:
        notes.append("Неустойка ограничена стоимостью устранения недостатков (правило из конфига).")
    if excluded:
        notes.append("Из расчёта исключены мораторные периоды — см. таблицу с основаниями.")

    return CalculationResult(
        mode="defects",
        period_start=period.start if period else None,
        period_end=period.end if period else None,
        total_days=sum(segment.days for segment in segments),
        segments=segments,
        excluded=excluded,
        lines=lines,
        total=total,
        rate_mode=rate_mode,
        rate_mode_title=RATE_MODE_TITLES[rate_mode],
        warnings=config.review_warnings(used_params + extra_used),
        notes=notes,
        disclaimer=config.disclaimer,
        config_version=config.version,
    )
