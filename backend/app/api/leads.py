"""Приём заявок с сайта и из виджета калькулятора."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Calculation, Lead
from ..notifications import notify_new_lead
from ..schemas import LeadRequest
from .deps import Actor, client_ip, current_actor, lead_limiter

router = APIRouter(prefix="/api/v1", tags=["Заявки"])


@router.post("/leads", status_code=201, summary="Оставить заявку")
def create_lead(
    payload: LeadRequest, request: Request, session: Session = Depends(get_session)
) -> dict:
    # Ловушка для ботов: людям это поле не видно, оно должно быть пустым.
    # Отвечаем как при успехе, чтобы бот не подбирал обход.
    if payload.website.strip():
        return {"ok": True, "id": None}

    lead_limiter.check(client_ip(request))

    if not payload.consent:
        raise HTTPException(
            status_code=400,
            detail="Без согласия на обработку персональных данных заявка не принимается.",
        )

    if payload.calculation_id and session.get(Calculation, payload.calculation_id) is None:
        raise HTTPException(status_code=400, detail="Расчёт с указанным идентификатором не найден.")

    lead = Lead(
        name=payload.name.strip(),
        phone=payload.phone.strip(),
        email=(payload.email or "").strip() or None,
        topic=payload.topic,
        region=payload.region,
        project=payload.project,
        comment=payload.comment,
        calculation_id=payload.calculation_id,
        consent_given=True,
        consent_at=datetime.now(timezone.utc),
        consent_policy_version=payload.consent_policy_version,
        consent_ip=client_ip(request),
        source=payload.source,
        page_url=payload.page_url,
    )
    session.add(lead)
    session.commit()

    notify_new_lead(lead)
    return {"ok": True, "id": lead.id}


@router.get("/leads", summary="Список заявок")
def list_leads(
    limit: int = 50,
    offset: int = 0,
    _: Actor = Depends(current_actor),
    session: Session = Depends(get_session),
) -> dict:
    limit = max(1, min(limit, 200))
    statement = select(Lead).order_by(Lead.created_at.desc()).limit(limit).offset(offset)
    leads = session.scalars(statement).all()
    return {
        "count": len(leads),
        "items": [
            {
                "id": lead.id,
                "created_at": lead.created_at.isoformat(),
                "name": lead.name,
                "phone": lead.phone,
                "email": lead.email,
                "topic": lead.topic,
                "region": lead.region,
                "project": lead.project,
                "comment": lead.comment,
                "status": lead.status,
                "source": lead.source,
                "calculation_id": lead.calculation_id,
                "calculation_total": (
                    lead.calculation.result.get("total_display") if lead.calculation else None
                ),
                "consent_at": lead.consent_at.isoformat() if lead.consent_at else None,
            }
            for lead in leads
        ],
    }
