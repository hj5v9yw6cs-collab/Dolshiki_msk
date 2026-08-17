"""Админские эндпоинты: правка юридического конфига и синхронизация ставки.

Правка конфига — операция с юридическими последствиями, поэтому каждая
запись проходит валидацию до сохранения и попадает в журнал изменений
вместе с полным снимком конфига.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import cbr
from ..core.legal_config import LegalConfigError, store
from ..db import get_session
from ..models import ConfigChange
from ..schemas import ConfigUpdateRequest
from .deps import require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["Администрирование"])

TRACKED_SECTIONS = (
    "day_count_rule",
    "cbr_rates",
    "moratoriums",
    "rate_caps",
    "delay_penalty",
    "defects_penalty",
    "consumer_penalty",
    "disclaimer",
)


def summarize_changes(before: Dict[str, Any], after: Dict[str, Any]) -> str:
    changed: List[str] = [
        section
        for section in TRACKED_SECTIONS
        if before.get(section) != after.get(section)
    ]
    return ", ".join(changed) if changed else "изменений в юридических параметрах нет"


@router.get("/legal-config", summary="Конфиг целиком (для формы редактирования)")
def read_config(_: str = Depends(require_admin)) -> dict:
    return store.get().raw


@router.put("/legal-config", summary="Сохранить конфиг")
def update_config(
    payload: ConfigUpdateRequest,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    before = store.get()
    before_raw = before.raw

    try:
        updated = store.save(payload.config, author=payload.author)
    except LegalConfigError as exc:
        # Конфиг не записан: сначала валидация, потом запись.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    summary = summarize_changes(before_raw, updated.raw)
    if payload.comment:
        summary = f"{summary}. Комментарий: {payload.comment}"

    session.add(
        ConfigChange(
            author=payload.author,
            version_before=before.version,
            version_after=updated.version,
            diff_summary=summary,
            snapshot=updated.raw,
        )
    )
    session.commit()

    return {
        "ok": True,
        "version": updated.version,
        "changed": summary,
        "pending_lawyer_review": updated.review_warnings(
            ["day_count", "rates", "delay_penalty", "defects_penalty", "consumer_penalty"]
        ),
    }


@router.get("/legal-config/history", summary="Журнал правок конфига")
def config_history(
    limit: int = 50,
    _: str = Depends(require_admin),
    session: Session = Depends(get_session),
) -> dict:
    limit = max(1, min(limit, 200))
    statement = select(ConfigChange).order_by(ConfigChange.created_at.desc()).limit(limit)
    changes = session.scalars(statement).all()
    return {
        "count": len(changes),
        "items": [
            {
                "id": change.id,
                "created_at": change.created_at.isoformat(),
                "author": change.author,
                "version_before": change.version_before,
                "version_after": change.version_after,
                "changed": change.diff_summary,
            }
            for change in changes
        ],
    }


@router.post("/rate/sync", summary="Синхронизировать ключевую ставку с cbr.ru")
def sync_rate(_: str = Depends(require_admin)) -> dict:
    return cbr.sync_rates(store)


@router.post("/legal-config/reload", summary="Перечитать конфиг с диска")
def reload_config(_: str = Depends(require_admin)) -> dict:
    config = store.reload()
    return {"ok": True, "version": config.version, "updated_at": config.updated_at}
