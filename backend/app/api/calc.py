"""Эндпоинты расчёта."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..core import cbr
from ..core.calculator import (
    CalculationError,
    DefectsInput,
    DelayInput,
    ExpenseInput,
    calculate_defects,
    calculate_delay,
)
from ..core.legal_config import LegalConfigError, store
from ..db import get_session
from ..models import Calculation
from ..presenters import result_to_dict
from ..print_view import render_print_page
from ..schemas import DefectsRequest, DelayRequest
from .deps import calc_limiter, client_ip

router = APIRouter(prefix="/api/v1", tags=["Калькулятор"])


def _expenses(items) -> list[ExpenseInput]:
    return [ExpenseInput(title=item.title, amount=item.amount, code=item.code) for item in items]


def _persist(session: Session, mode: str, payload: dict, result: dict, source: str) -> str:
    record = Calculation(
        mode=mode,
        inputs=payload,
        result=result,
        total=Decimal(result["total"]),
        config_version=result.get("config_version", 0),
        source=source,
    )
    session.add(record)
    session.commit()
    return record.id


def _respond(result_dict: dict, calculation_id: str) -> dict:
    return {
        **result_dict,
        "calculation_id": calculation_id,
        "rate_status": cbr.rate_status(store.get()),
    }


@router.post("/calc/delay", summary="Неустойка за просрочку передачи объекта")
def calc_delay(
    payload: DelayRequest, request: Request, session: Session = Depends(get_session)
) -> dict:
    calc_limiter.check(client_ip(request))
    try:
        result = calculate_delay(
            DelayInput(
                contract_price=payload.contract_price,
                due_date=payload.due_date,
                actual_date=payload.actual_date,
                is_individual=payload.is_individual,
                rate_mode=payload.rate_mode,
                manual_rate=payload.manual_rate,
                claim_date=payload.claim_date,
                moral_harm=payload.moral_harm,
                include_consumer_penalty=payload.include_consumer_penalty,
                expenses=_expenses(payload.expenses),
            ),
            store.get(),
        )
    except (CalculationError, LegalConfigError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    body = result_to_dict(result)
    calculation_id = _persist(
        session, "delay", payload.model_dump(mode="json"), body, payload.source
    )
    return _respond(body, calculation_id)


@router.post("/calc/defects", summary="Недостатки отделки: устранение и неустойка")
def calc_defects(
    payload: DefectsRequest, request: Request, session: Session = Depends(get_session)
) -> dict:
    calc_limiter.check(client_ip(request))
    try:
        result = calculate_defects(
            DefectsInput(
                repair_cost=payload.repair_cost,
                demand_served_date=payload.demand_served_date,
                satisfied_date=payload.satisfied_date,
                expertise_cost=payload.expertise_cost,
                rate_mode=payload.rate_mode,
                manual_rate=payload.manual_rate,
                claim_date=payload.claim_date,
                moral_harm=payload.moral_harm,
                include_consumer_penalty=payload.include_consumer_penalty,
                include_repair_cost_in_total=payload.include_repair_cost_in_total,
                expenses=_expenses(payload.expenses),
            ),
            store.get(),
        )
    except (CalculationError, LegalConfigError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    body = result_to_dict(result)
    calculation_id = _persist(
        session, "defects", payload.model_dump(mode="json"), body, payload.source
    )
    return _respond(body, calculation_id)


@router.get("/calc/{calculation_id}", summary="Сохранённый расчёт")
def get_calculation(calculation_id: str, session: Session = Depends(get_session)) -> dict:
    record = session.get(Calculation, calculation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Расчёт не найден.")
    return {**record.result, "calculation_id": record.id}


@router.get(
    "/calc/{calculation_id}/print",
    response_class=HTMLResponse,
    summary="Печатная форма расчёта (приложение к иску)",
)
def print_calculation(calculation_id: str, session: Session = Depends(get_session)) -> HTMLResponse:
    record = session.get(Calculation, calculation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Расчёт не найден.")
    return HTMLResponse(render_print_page(record.result, record.created_at))


@router.get("/rate", summary="Текущая ключевая ставка и свежесть данных")
def rate_status() -> dict:
    return cbr.rate_status(store.get())


@router.get("/legal-config", summary="Действующий юридический конфиг (только чтение)")
def legal_config() -> dict:
    config = store.get()
    return {
        "version": config.version,
        "updated_at": config.updated_at,
        "updated_by": config.updated_by,
        "day_count_rule": config.raw.get("day_count_rule"),
        "moratoriums": config.raw.get("moratoriums"),
        "rate_caps": config.raw.get("rate_caps"),
        "delay_penalty": config.raw.get("delay_penalty"),
        "defects_penalty": config.raw.get("defects_penalty"),
        "consumer_penalty": config.raw.get("consumer_penalty"),
        "disclaimer": config.disclaimer,
        "pending_lawyer_review": config.review_warnings(
            ["day_count", "rates", "delay_penalty", "defects_penalty", "consumer_penalty"]
        ),
    }
