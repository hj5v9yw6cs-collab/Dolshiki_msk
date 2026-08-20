"""Дела: список, карточка, движение по воронке, лента событий."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from ..casework import (
    REGIONS,
    ROLES,
    SERVICE_TYPES,
    STAGE_BY_CODE,
    default_claim_deadline,
    is_valid_stage,
    next_deadline,
    stage_catalog,
    stage_title,
)
from ..db import DATA_DIR, get_session
from ..models import Case, CaseEvent, Client, Developer, Document, DocumentAccess, Lead, User
from ..presenters import format_money
from ..schemas import CaseCreate, CaseUpdate, LeadConvert, NoteCreate, StageChange
from .deps import Actor, current_actor, require_manager

router = APIRouter(prefix="/api/v1", tags=["Дела"])

# Поля, правки которых попадают в ленту дела.
TRACKED_FIELDS = {
    "service_type": "тип услуги",
    "region": "регион",
    "lawyer_id": "ответственный юрист",
    "project": "ЖК",
    "apartment": "квартира",
    "contract_number": "номер ДДУ",
    "contract_date": "дата ДДУ",
    "contract_price": "цена ДДУ",
    "due_date": "срок передачи по договору",
    "actual_transfer_date": "дата фактической передачи",
    "claim_sent_on": "дата направления претензии",
    "claim_response_deadline": "срок ответа на претензию",
    "court_name": "суд",
    "court_case_number": "номер дела в суде",
    "next_hearing_on": "дата заседания",
    "appeal_deadline": "срок обжалования",
    "amount_claimed": "заявлено",
    "amount_awarded": "присуждено",
    "amount_received": "получено",
    "fee": "гонорар",
}

MONEY_FIELDS = ("contract_price", "amount_claimed", "amount_awarded", "amount_received", "fee")


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def _money(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


def _money_display(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else format_money(value)


def _iso(value) -> Optional[str]:
    return value.isoformat() if value else None


def next_case_number(session: DbSession, today: Optional[date] = None) -> str:
    """Номер вида 2026-014: год и порядковый номер внутри года."""
    today = today or date.today()
    prefix = f"{today.year}-"
    used = session.scalars(select(Case.number).where(Case.number.like(f"{prefix}%"))).all()
    numbers = []
    for value in used:
        tail = value.split("-", 1)[1]
        if tail.isdigit():
            numbers.append(int(tail))
    return f"{prefix}{(max(numbers) + 1) if numbers else 1:03d}"


def log_event(session: DbSession, case: Case, actor: Actor, kind: str, text: str) -> CaseEvent:
    event = CaseEvent(
        case_id=case.id, kind=kind, text=text,
        author_id=actor.user_id, author_name=actor.display_name,
    )
    session.add(event)
    return event


def find_or_create_developer(session: DbSession, name: Optional[str]) -> Optional[Developer]:
    name = (name or "").strip()
    if not name:
        return None
    key = name.casefold()
    existing = session.scalars(select(Developer).where(Developer.name_key == key)).first()
    if existing:
        return existing
    developer = Developer(name=name, name_key=key)
    session.add(developer)
    session.flush()
    return developer


def case_brief(case: Case, actor: Actor, today: Optional[date] = None) -> dict:
    deadline = next_deadline(case, today)
    return {
        "id": case.id,
        "number": case.number,
        "created_at": case.created_at.isoformat(),
        "client_name": case.client.full_name if case.client else "",
        "client_phone": case.client.phone if case.client else "",
        "project": case.project,
        "developer": case.developer.name if case.developer else None,
        "service_type": case.service_type,
        "service_title": SERVICE_TYPES.get(case.service_type, case.service_type),
        "region": case.region,
        "region_title": REGIONS.get(case.region, case.region),
        "stage": case.stage,
        "stage_title": stage_title(case.stage),
        "lawyer_id": case.lawyer_id,
        "lawyer_name": case.lawyer.name if case.lawyer else None,
        "amount_claimed": _money(case.amount_claimed),
        "amount_claimed_display": _money_display(case.amount_claimed),
        "amount_awarded_display": _money_display(case.amount_awarded),
        "deadline": None if deadline is None else {
            "kind": deadline.kind,
            "title": deadline.title,
            "due_on": deadline.due_on.isoformat(),
            "days_left": deadline.days_left,
            "is_overdue": deadline.is_overdue,
            "is_soon": deadline.is_soon,
        },
    }


def case_detail(case: Case, actor: Actor, today: Optional[date] = None) -> dict:
    data = case_brief(case, actor, today)
    data.update({
        "client_id": case.client_id,
        "client_email": case.client.email if case.client else None,
        "client_birth_date": _iso(case.client.birth_date) if case.client else None,
        "client_passport": case.client.passport if case.client else None,
        "client_snils": case.client.snils if case.client else None,
        "client_inn": case.client.inn if case.client else None,
        "client_address": case.client.address if case.client else None,
        "apartment": case.apartment,
        "object_address": case.object_address,
        "area": None if case.area is None else str(case.area),
        "developer_id": case.developer_id,
        "developer_inn": case.developer.inn if case.developer else None,
        "developer_ogrn": case.developer.ogrn if case.developer else None,
        "developer_address": case.developer.address if case.developer else None,
        "contract_number": case.contract_number,
        "contract_date": _iso(case.contract_date),
        "contract_price": _money(case.contract_price),
        "contract_price_display": _money_display(case.contract_price),
        "due_date": _iso(case.due_date),
        "actual_transfer_date": _iso(case.actual_transfer_date),
        "claim_sent_on": _iso(case.claim_sent_on),
        "claim_response_deadline": _iso(case.claim_response_deadline),
        "claim_track_number": case.claim_track_number,
        "lawsuit_sent_on": _iso(case.lawsuit_sent_on),
        "lawsuit_track_number": case.lawsuit_track_number,
        "court_name": case.court_name,
        "court_case_number": case.court_case_number,
        "next_hearing_on": _iso(case.next_hearing_on),
        "appeal_deadline": _iso(case.appeal_deadline),
        "moral_damage": _money(case.moral_damage),
        "duty": _money(case.duty),
        "amount_awarded": _money(case.amount_awarded),
        "amount_received": _money(case.amount_received),
        "amount_received_display": _money_display(case.amount_received),
        "calculation_id": case.calculation_id,
        "lead_id": case.lead_id,
        "comment": case.comment,
        "closed_at": case.closed_at.isoformat() if case.closed_at else None,
        "events": [
            {
                "id": event.id,
                "created_at": event.created_at.isoformat(),
                "author": event.author_name,
                "kind": event.kind,
                "text": event.text,
            }
            for event in case.events
        ],
    })
    # Гонорар — только руководителю.
    if actor.is_manager:
        data["fee"] = _money(case.fee)
        data["fee_display"] = _money_display(case.fee)
    return data


# ---------------------------------------------------------------------------
# Справочники
# ---------------------------------------------------------------------------


@router.get("/meta", summary="Справочники для интерфейса")
def meta(actor: Actor = Depends(current_actor), session: DbSession = Depends(get_session)) -> dict:
    users = session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.name)).all()
    return {
        "stages": stage_catalog(),
        "services": [{"code": code, "title": title} for code, title in SERVICE_TYPES.items()],
        "regions": [{"code": code, "title": title} for code, title in REGIONS.items()],
        "roles": [{"code": code, "title": title} for code, title in ROLES.items()],
        "users": [{"id": u.id, "name": u.name, "role": u.role} for u in users],
        "can_see_money": actor.is_manager,
    }


@router.get("/dashboard", summary="Сводка по делам")
def dashboard(
    actor: Actor = Depends(current_actor), session: DbSession = Depends(get_session)
) -> dict:
    today = date.today()
    cases = session.scalars(select(Case)).all()

    by_stage: dict[str, int] = {}
    overdue: List[dict] = []
    soon: List[dict] = []
    active = 0

    for case in cases:
        by_stage[case.stage] = by_stage.get(case.stage, 0) + 1
        stage = STAGE_BY_CODE.get(case.stage)
        if stage and not stage.is_final:
            active += 1
        brief = case_brief(case, actor, today)
        deadline = brief["deadline"]
        if deadline and deadline["is_overdue"]:
            overdue.append(brief)
        elif deadline and deadline["is_soon"]:
            soon.append(brief)

    overdue.sort(key=lambda item: item["deadline"]["due_on"])
    soon.sort(key=lambda item: item["deadline"]["due_on"])

    summary = {
        "total": len(cases),
        "active": active,
        "by_stage": by_stage,
        "overdue": overdue,
        "soon": soon,
        "new_leads": session.scalar(select(func.count()).select_from(Lead).where(Lead.status == "new")) or 0,
    }
    if actor.is_manager:
        awarded = session.scalar(select(func.sum(Case.amount_awarded))) or Decimal(0)
        received = session.scalar(select(func.sum(Case.amount_received))) or Decimal(0)
        summary["money"] = {
            "awarded": str(awarded), "awarded_display": format_money(awarded),
            "received": str(received), "received_display": format_money(received),
        }
    return summary


# ---------------------------------------------------------------------------
# Дела
# ---------------------------------------------------------------------------


@router.get("/cases", summary="Список дел")
def list_cases(
    stage: Optional[str] = None,
    lawyer_id: Optional[str] = None,
    region: Optional[str] = None,
    service_type: Optional[str] = None,
    q: Optional[str] = None,
    only_active: bool = False,
    only_overdue: bool = False,
    limit: int = Query(default=200, ge=1, le=500),
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    statement = select(Case).join(Client, Case.client_id == Client.id)

    if stage:
        statement = statement.where(Case.stage == stage)
    if lawyer_id:
        statement = statement.where(Case.lawyer_id == lawyer_id)
    if region:
        statement = statement.where(Case.region == region)
    if service_type:
        statement = statement.where(Case.service_type == service_type)
    if only_active:
        final = [code for code, item in STAGE_BY_CODE.items() if item.is_final]
        statement = statement.where(Case.stage.not_in(final))
    if q:
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Client.full_name.ilike(pattern),
                Client.phone.ilike(pattern),
                Case.number.ilike(pattern),
                Case.project.ilike(pattern),
                Case.court_case_number.ilike(pattern),
            )
        )

    cases = session.scalars(statement.order_by(Case.created_at.desc()).limit(limit)).all()
    today = date.today()
    items = [case_brief(case, actor, today) for case in cases]
    if only_overdue:
        items = [item for item in items if item["deadline"] and item["deadline"]["is_overdue"]]
    return {"count": len(items), "items": items}


@router.post("/cases", status_code=201, summary="Завести дело")
def create_case(
    payload: CaseCreate,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    if not is_valid_stage(payload.stage):
        raise HTTPException(status_code=400, detail=f"Неизвестная стадия: {payload.stage}")
    if payload.service_type not in SERVICE_TYPES:
        raise HTTPException(status_code=400, detail=f"Неизвестный тип услуги: {payload.service_type}")

    client = Client(
        full_name=payload.client_name.strip(),
        phone=payload.client_phone.strip(),
        email=(payload.client_email or "").strip() or None,
        region=payload.region,
    )
    session.add(client)
    session.flush()

    developer = find_or_create_developer(session, payload.developer_name)

    case = Case(
        number=next_case_number(session),
        client_id=client.id,
        developer_id=developer.id if developer else None,
        lawyer_id=payload.lawyer_id or actor.user_id,
        service_type=payload.service_type,
        region=payload.region,
        stage=payload.stage,
        project=payload.project,
        apartment=payload.apartment,
        contract_number=payload.contract_number,
        contract_date=payload.contract_date,
        contract_price=payload.contract_price,
        due_date=payload.due_date,
        actual_transfer_date=payload.actual_transfer_date,
        calculation_id=payload.calculation_id,
        lead_id=payload.lead_id,
        comment=payload.comment,
    )
    session.add(case)
    session.flush()
    log_event(session, case, actor, "system", f"Дело заведено на стадии «{stage_title(case.stage)}».")
    session.commit()
    session.refresh(case)
    return case_detail(case, actor)


@router.get("/cases/{case_id}", summary="Карточка дела")
def get_case(
    case_id: str,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело не найдено.")
    return case_detail(case, actor)


@router.patch("/cases/{case_id}", summary="Изменить дело")
def update_case(
    case_id: str,
    payload: CaseUpdate,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело не найдено.")

    changes = payload.model_dump(exclude_unset=True)

    if "fee" in changes and not actor.is_manager:
        raise HTTPException(status_code=403, detail="Гонорар правит только руководитель.")
    if changes.get("service_type") and changes["service_type"] not in SERVICE_TYPES:
        raise HTTPException(status_code=400, detail="Неизвестный тип услуги.")
    if changes.get("region") and changes["region"] not in REGIONS:
        raise HTTPException(status_code=400, detail="Неизвестный регион.")
    if changes.get("lawyer_id") and session.get(User, changes["lawyer_id"]) is None:
        raise HTTPException(status_code=400, detail="Такого сотрудника нет.")

    # Данные клиента лежат в своей таблице.
    client = case.client
    client_fields = (
        ("client_name", "full_name"), ("client_phone", "phone"), ("client_email", "email"),
        ("client_birth_date", "birth_date"), ("client_passport", "passport"),
        ("client_snils", "snils"), ("client_inn", "inn"), ("client_address", "address"),
    )
    for field, attribute in client_fields:
        if field in changes:
            value = changes.pop(field)
            if attribute in ("full_name", "phone"):
                setattr(client, attribute, value)
            else:
                # Пустая строка из формы — это «стереть», а не значение.
                setattr(client, attribute, (value or None) if not isinstance(value, str) else (value.strip() or None))

    if "developer_name" in changes:
        developer = find_or_create_developer(session, changes.pop("developer_name"))
        case.developer_id = developer.id if developer else None

    notes: List[str] = []
    for field, value in changes.items():
        before = getattr(case, field)
        if before == value:
            continue
        setattr(case, field, value)
        if field in TRACKED_FIELDS:
            notes.append(
                f"{TRACKED_FIELDS[field]}: "
                f"{_readable(before, field, session)} → {_readable(value, field, session)}"
            )

    # Направили претензию — сразу ставим срок ответа, если его не задали руками.
    if changes.get("claim_sent_on") and "claim_response_deadline" not in changes:
        case.claim_response_deadline = default_claim_deadline(changes["claim_sent_on"])
        notes.append(
            f"срок ответа на претензию: {case.claim_response_deadline.strftime('%d.%m.%Y')} (по умолчанию)"
        )

    if notes:
        log_event(session, case, actor, "field", "; ".join(notes))
    session.commit()
    session.refresh(case)
    return case_detail(case, actor)


def _readable(value, field: str, session: DbSession) -> str:
    if value in (None, ""):
        return "—"
    if field == "lawyer_id":
        user = session.get(User, value)
        return user.name if user else str(value)
    if field == "service_type":
        return SERVICE_TYPES.get(value, str(value))
    if field == "region":
        return REGIONS.get(value, str(value))
    if field in MONEY_FIELDS:
        return f"{format_money(Decimal(str(value)))} ₽"
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    return str(value)


@router.delete("/cases/{case_id}", summary="Удалить дело")
def delete_case(
    case_id: str,
    actor: Actor = Depends(require_manager),
    session: DbSession = Depends(get_session),
) -> dict:
    """Удаляет дело со всеми документами и лентой.

    Только руководитель: в деле лежат паспорта и договоры клиента, и это
    действие необратимо. Вместе с делом уходят файлы с диска, записи ленты
    и журнал доступа к его документам — по 152-ФЗ хранить их после удаления
    самих данных незачем.

    Клиент остаётся: у него могут быть другие дела. Если это было
    единственное, удаляется и он — иначе в базе копятся паспортные данные
    людей, дела которых закрыты и стёрты.
    """
    from ..documents import case_folder  # локально: модуль тянет разбор документов

    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело не найдено.")

    number, client = case.number, case.client

    folder = case_folder(
        DATA_DIR, case.number, client.full_name if client else "", case.created_at.date()
    )
    for document in session.scalars(select(Document).where(Document.case_id == case.id)):
        (folder / document.folder / document.stored_name).unlink(missing_ok=True)
        session.delete(document)

    for access in session.scalars(select(DocumentAccess).where(DocumentAccess.case_id == case.id)):
        session.delete(access)
    for event in session.scalars(select(CaseEvent).where(CaseEvent.case_id == case.id)):
        session.delete(event)

    session.delete(case)
    session.flush()

    if client is not None:
        others = session.scalars(select(Case).where(Case.client_id == client.id)).first()
        if others is None:
            session.delete(client)

    session.commit()

    # Пустые папки дела остаются на диске: файлов в них уже нет, а удалять
    # каталоги рекурсивно из обработчика — лишний риск ошибиться путём.
    return {"ok": True, "number": number}


@router.post("/cases/{case_id}/stage", summary="Перевести на другую стадию")
def change_stage(
    case_id: str,
    payload: StageChange,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело не найдено.")
    if not is_valid_stage(payload.stage):
        raise HTTPException(status_code=400, detail=f"Неизвестная стадия: {payload.stage}")
    if payload.stage == case.stage:
        return case_detail(case, actor)

    was = stage_title(case.stage)
    case.stage = payload.stage
    stage = STAGE_BY_CODE[payload.stage]
    case.closed_at = datetime.now(timezone.utc) if stage.is_final else None

    text = f"Стадия: {was} → {stage.title}"
    if payload.comment.strip():
        text += f". {payload.comment.strip()}"
    log_event(session, case, actor, "stage", text)
    session.commit()
    session.refresh(case)
    return case_detail(case, actor)


@router.post("/cases/{case_id}/notes", status_code=201, summary="Добавить заметку")
def add_note(
    case_id: str,
    payload: NoteCreate,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело не найдено.")
    log_event(session, case, actor, "note", payload.text.strip())
    session.commit()
    session.refresh(case)
    return case_detail(case, actor)


@router.post("/leads/{lead_id}/convert", status_code=201, summary="Завести дело из заявки")
def convert_lead(
    lead_id: str,
    payload: LeadConvert,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    lead = session.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена.")

    existing = session.scalars(select(Case).where(Case.lead_id == lead.id)).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"По этой заявке уже заведено дело № {existing.number}.",
        )

    service_type = payload.service_type or ("defects" if lead.topic == "defects" else "delay")
    if service_type not in SERVICE_TYPES:
        raise HTTPException(status_code=400, detail="Неизвестный тип услуги.")

    client = Client(
        full_name=lead.name, phone=lead.phone, email=lead.email, region=lead.region,
    )
    session.add(client)
    session.flush()

    case = Case(
        number=next_case_number(session),
        client_id=client.id,
        lawyer_id=payload.lawyer_id or actor.user_id,
        service_type=service_type,
        region=lead.region or "msk",
        stage="qualification",
        project=lead.project,
        calculation_id=lead.calculation_id,
        lead_id=lead.id,
        comment=lead.comment,
    )
    session.add(case)
    session.flush()

    text = "Дело заведено из заявки с сайта."
    if lead.calculation:
        total = lead.calculation.result.get("total_display")
        if total:
            case.amount_claimed = Decimal(lead.calculation.result.get("total", "0"))
            text += f" Предварительный расчёт с сайта: {total} ₽."
    log_event(session, case, actor, "system", text)

    lead.status = "converted"
    session.commit()
    session.refresh(case)
    return case_detail(case, actor)


@router.get("/cases.xlsx", summary="Выгрузить реестр дел в Excel")
def export_registry(
    stage: Optional[str] = None,
    lawyer_id: Optional[str] = None,
    region: Optional[str] = None,
    only_active: bool = False,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
):
    from fastapi.responses import Response

    from ..registry import build_registry, registry_filename

    statement = select(Case)
    if stage:
        statement = statement.where(Case.stage == stage)
    if lawyer_id:
        statement = statement.where(Case.lawyer_id == lawyer_id)
    if region:
        statement = statement.where(Case.region == region)
    if only_active:
        final = [code for code, item in STAGE_BY_CODE.items() if item.is_final]
        statement = statement.where(Case.stage.not_in(final))

    cases = session.scalars(statement.order_by(Case.number)).all()
    payload = build_registry(cases, with_money=actor.is_manager)
    filename = registry_filename()

    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
