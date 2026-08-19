"""Документы по делу: приём, раскладка, выдача, журнал доступа."""

from __future__ import annotations

import logging
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import DATA_DIR, get_session
from ..documents import (
    DOC_TYPE_BY_CODE,
    FOLDERS,
    StorageError,
    build_checklist,
    build_filename,
    case_folder,
    catalog,
    check_upload,
    classify,
    extract_requisites,
    extract_text,
    looks_like_scan,
    resolve_target,
    save_stream,
    type_folder,
    type_title,
    unique_path,
)
from ..models import Case, Document, DocumentAccess
from ..schemas import DocumentUpdate
from .cases import log_event
from .deps import Actor, client_ip, current_actor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["Документы"])

# Реквизиты, которые можно перенести из документа в карточку дела.
APPLICABLE = {
    "contract_number": "номер ДДУ",
    "contract_date": "дата ДДУ",
    "contract_price": "цена ДДУ",
    "apartment": "квартира",
    "due_date": "срок передачи по договору",
}


def _incoming_dir() -> Path:
    """Папка для файла, который ещё не прошёл проверки.

    Лежит внутри DATA_DIR, а не в /tmp, и это принципиально: готовый файл
    переносится в папку дела через os.replace, а он работает только в
    пределах одной файловой системы. В контейнере /tmp — слой образа, а
    data — примонтированный том, и перенос между ними падает с
    OSError: [Errno 18] Invalid cross-device link.
    """
    path = DATA_DIR / ".incoming"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _case_root(case: Case) -> Path:
    return case_folder(DATA_DIR, case.number, case.client.full_name if case.client else "",
                       case.created_at.date())


def _document_payload(document: Document) -> dict:
    return {
        "id": document.id,
        "created_at": document.created_at.isoformat(),
        "original_name": document.original_name,
        "stored_name": document.stored_name,
        "folder": document.folder,
        "folder_title": FOLDERS.get(document.folder, document.folder),
        "doc_type": document.doc_type,
        "doc_type_title": type_title(document.doc_type),
        "doc_date": document.doc_date.isoformat() if document.doc_date else None,
        "size_bytes": document.size_bytes,
        "size_display": f"{document.size_bytes / 1024 / 1024:.1f} МБ"
        if document.size_bytes >= 1024 * 1024 else f"{max(document.size_bytes // 1024, 1)} КБ",
        "confidence": round(document.confidence, 2),
        "needs_review": document.needs_review,
        "detected_by": document.detected_by,
        "signals": document.signals,
        "is_scan": document.is_scan,
        "extracted": document.extracted or {},
        "extracted_applied": document.extracted_applied,
        "uploaded_by": document.uploaded_by_name,
        "note": document.note,
    }


def _get_case(session: DbSession, case_id: str) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Дело не найдено.")
    return case


@router.get("/documents/meta", summary="Справочник типов документов")
def documents_meta(_: Actor = Depends(current_actor)) -> dict:
    return {
        "types": catalog(),
        "folders": [{"code": code, "title": title} for code, title in FOLDERS.items()],
    }


@router.get("/cases/{case_id}/documents", summary="Документы дела и комплектность")
def list_documents(
    case_id: str,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    case = _get_case(session, case_id)
    documents = session.scalars(
        select(Document).where(Document.case_id == case_id).order_by(Document.created_at.desc())
    ).all()

    # В комплектность идут только подтверждённые типы: иначе «похоже на
    # паспорт» закроет пункт, которого на самом деле нет.
    confirmed = [item.doc_type for item in documents if not item.needs_review]

    return {
        "count": len(documents),
        "items": [_document_payload(item) for item in documents],
        "checklist": build_checklist(case.stage, confirmed),
        "needs_review": sum(1 for item in documents if item.needs_review),
    }


@router.post("/cases/{case_id}/documents", status_code=201, summary="Загрузить документ")
async def upload_document(
    case_id: str,
    request: Request,
    file: UploadFile = File(...),
    doc_type: Optional[str] = Form(default=None),
    note: Optional[str] = Form(default=None),
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    case = _get_case(session, case_id)
    original_name = file.filename or "file"

    # Файл сначала уходит во временный, чтобы не мусорить в папке дела,
    # если он не пройдёт проверки.
    with tempfile.NamedTemporaryFile(delete=False, dir=_incoming_dir()) as handle:
        temporary = Path(handle.name)
    try:
        try:
            size, digest = save_stream(file.file, temporary)
            suffix = check_upload(original_name, size)
        except StorageError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        duplicate = session.scalars(
            select(Document).where(Document.case_id == case_id, Document.sha256 == digest)
        ).first()
        if duplicate is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Такой файл уже загружен: {duplicate.stored_name}",
            )

        text = extract_text(temporary, original_name)
        is_scan = looks_like_scan(temporary, original_name, text)

        if doc_type and doc_type in DOC_TYPE_BY_CODE:
            code, confidence, signals, detected_by = doc_type, 1.0, "указан вручную", "manual"
            needs_review = False
        else:
            guess = classify(original_name, text)
            code, confidence = guess.code, guess.confidence
            signals, detected_by = guess.explanation, "rules"
            needs_review = guess.needs_review

        requisites = extract_requisites(text, code)
        doc_date = requisites.contract_date if code in ("ddu", "ddu_amendment") else None

        folder = type_folder(code)
        stored_name = build_filename(
            case.number, case.client.full_name if case.client else "", code, doc_date, suffix
        )
        try:
            target = unique_path(resolve_target(_case_root(case), folder, stored_name))
        except StorageError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(target)

        document = Document(
            case_id=case.id,
            original_name=original_name,
            stored_name=target.name,
            relative_path=f"{folder}/{target.name}",
            folder=folder,
            doc_type=code,
            doc_date=doc_date,
            size_bytes=size,
            sha256=digest,
            confidence=confidence,
            needs_review=needs_review,
            detected_by=detected_by,
            signals=signals,
            is_scan=is_scan,
            extracted=requisites.as_dict(),
            uploaded_by_id=actor.user_id,
            uploaded_by_name=actor.display_name,
            note=note,
        )
        session.add(document)

        text_note = f"Загружен документ: {target.name} ({type_title(code)})"
        if needs_review:
            text_note += " — тип определён неуверенно, нужна проверка"
        log_event(session, case, actor, "system", text_note)
        session.commit()
        session.refresh(document)
        return _document_payload(document)
    finally:
        temporary.unlink(missing_ok=True)


@router.patch("/documents/{document_id}", summary="Изменить документ")
def update_document(
    document_id: str,
    payload: DocumentUpdate,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден.")

    changes = payload.model_dump(exclude_unset=True)

    if "doc_type" in changes:
        code = changes["doc_type"]
        if code not in DOC_TYPE_BY_CODE:
            raise HTTPException(status_code=400, detail="Неизвестный тип документа.")
        if code != document.doc_type:
            case = document.case
            new_folder = type_folder(code)
            root = _case_root(case)
            old_path = root / document.folder / document.stored_name
            new_name = build_filename(
                case.number, case.client.full_name if case.client else "",
                code, document.doc_date, Path(document.stored_name).suffix,
            )
            try:
                new_path = unique_path(resolve_target(root, new_folder, new_name))
            except StorageError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error

            if old_path.exists():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                old_path.replace(new_path)

            log_event(
                session, case, actor, "system",
                f"Тип документа {document.stored_name}: "
                f"{type_title(document.doc_type)} → {type_title(code)}",
            )
            document.folder = new_folder
            document.stored_name = new_path.name
            document.relative_path = f"{new_folder}/{new_path.name}"

        document.doc_type = code
        document.detected_by = "manual"
        document.confidence = 1.0
        document.needs_review = False
        document.signals = "указан вручную"

    if "doc_date" in changes:
        document.doc_date = changes["doc_date"]
    if "note" in changes:
        document.note = changes["note"]

    session.commit()
    session.refresh(document)
    return _document_payload(document)


@router.post("/documents/{document_id}/apply", summary="Перенести реквизиты в карточку дела")
def apply_requisites(
    document_id: str,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден.")

    extracted = document.extracted or {}
    if not extracted:
        raise HTTPException(status_code=400, detail="В документе не нашлось реквизитов.")

    case = document.case
    applied = []
    for field in APPLICABLE:  # словарь: имя поля -> как назвать его в ленте
        value = extracted.get(field)
        if value is None or getattr(case, field, None) not in (None, ""):
            continue  # заполненное вручную не перетираем
        setattr(case, field, date.fromisoformat(value) if field.endswith("_date") else value)
        applied.append(field)

    if not applied:
        raise HTTPException(
            status_code=409,
            detail="Все эти поля в карточке уже заполнены — автоматически ничего не меняем.",
        )

    document.extracted_applied = True
    log_event(
        session, case, actor, "field",
        "Из документа " + document.stored_name + " перенесено: "
        + ", ".join(APPLICABLE[field] for field in applied),
    )
    session.commit()
    return {"ok": True, "applied": applied}


@router.get("/documents/{document_id}/file", summary="Скачать документ")
def download_document(
    document_id: str,
    request: Request,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> FileResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден.")

    path = _case_root(document.case) / document.folder / document.stored_name
    if not path.exists():
        raise HTTPException(status_code=410, detail="Файл отсутствует на диске.")

    # Журнал доступа: кто и когда открыл документ клиента.
    session.add(DocumentAccess(
        document_id=document.id, case_id=document.case_id,
        user_id=actor.user_id, user_name=actor.display_name,
        action="download", ip=client_ip(request),
    ))
    session.commit()

    return FileResponse(path, filename=document.stored_name)


@router.delete("/documents/{document_id}", summary="Удалить документ")
def delete_document(
    document_id: str,
    request: Request,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден.")

    case = document.case
    path = _case_root(case) / document.folder / document.stored_name
    path.unlink(missing_ok=True)

    session.add(DocumentAccess(
        document_id=document.id, case_id=document.case_id,
        user_id=actor.user_id, user_name=actor.display_name,
        action="delete", ip=client_ip(request),
    ))
    log_event(session, case, actor, "system", f"Удалён документ: {document.stored_name}")
    session.delete(document)
    session.commit()
    return {"ok": True}


@router.get("/documents/{document_id}/access-log", summary="Кто открывал документ")
def access_log(
    document_id: str,
    actor: Actor = Depends(current_actor),
    session: DbSession = Depends(get_session),
) -> dict:
    records = session.scalars(
        select(DocumentAccess)
        .where(DocumentAccess.document_id == document_id)
        .order_by(DocumentAccess.created_at.desc())
        .limit(100)
    ).all()
    return {
        "count": len(records),
        "items": [
            {
                "created_at": record.created_at.isoformat(),
                "user": record.user_name,
                "action": record.action,
                "ip": record.ip,
            }
            for record in records
        ],
    }
