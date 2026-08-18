"""Общие зависимости API: доступ, роли и ограничение частоты."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..core.security import token_fingerprint
from ..db import get_session


class RateLimiter:
    """Простой лимитер в памяти.

    Хватает на один процесс, а при 30 делах в месяц больше одного и не
    нужно. Если когда-нибудь появятся несколько воркеров — заменить на Redis.
    """

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много запросов. Попробуйте через несколько минут.",
            )
        hits.append(now)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


lead_limiter = RateLimiter(limit=5, window_seconds=600)
calc_limiter = RateLimiter(limit=60, window_seconds=600)
login_limiter = RateLimiter(limit=10, window_seconds=300)


# ---------------------------------------------------------------------------
# Доступ
# ---------------------------------------------------------------------------


@dataclass
class Actor:
    """Кто выполняет запрос: сотрудник или служебный токен.

    Служебный доступ по ADMIN_TOKEN оставлен для скриптов и правки
    юридического конфига; он приравнен к роли руководителя.
    """

    role: str
    user: Optional[object] = None
    session_id: Optional[str] = None

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"

    @property
    def user_id(self) -> Optional[str]:
        return getattr(self.user, "id", None)

    @property
    def display_name(self) -> str:
        return getattr(self.user, "name", "служебный доступ")


def _bearer(authorization: str) -> str:
    prefix = "Bearer "
    return authorization[len(prefix):].strip() if authorization.startswith(prefix) else ""


def current_actor(
    authorization: str = Header(default=""),
    session: DbSession = Depends(get_session),
) -> Actor:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Требуется вход в систему.")

    admin_token = os.getenv("ADMIN_TOKEN", "").strip()
    if admin_token and token == admin_token:
        return Actor(role="manager")

    from ..models import Session as SessionModel  # локальный импорт: избегаем цикла

    record = session.scalars(
        select(SessionModel).where(SessionModel.token_hash == token_fingerprint(token))
    ).first()
    if record is None:
        raise HTTPException(status_code=401, detail="Сессия не найдена, войдите заново.")

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        session.delete(record)
        session.commit()
        raise HTTPException(status_code=401, detail="Сессия истекла, войдите заново.")

    user = record.user
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Учётная запись отключена.")

    return Actor(role=user.role, user=user, session_id=record.id)


def require_manager(actor: Actor = Depends(current_actor)) -> Actor:
    if not actor.is_manager:
        raise HTTPException(status_code=403, detail="Доступно только руководителю.")
    return actor


def require_admin(actor: Actor = Depends(require_manager)) -> Actor:
    """Совместимость с Фазой 1: правка конфига и выгрузка заявок."""
    return actor
