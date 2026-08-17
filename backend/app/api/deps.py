"""Общие зависимости API: доступ администратора и ограничение частоты."""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Header, HTTPException, Request, status


def require_admin(authorization: str = Header(default="")) -> str:
    """Доступ к админским эндпоинтам по токену из ADMIN_TOKEN.

    Если токен не задан в окружении — эндпоинт закрыт. Открывать его
    «по умолчанию» нельзя: за ним правка юридического конфига и выгрузка
    персональных данных.
    """
    expected = os.getenv("ADMIN_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_TOKEN не задан в окружении — админские эндпоинты отключены.",
        )
    prefix = "Bearer "
    provided = authorization[len(prefix):].strip() if authorization.startswith(prefix) else ""
    if not provided or provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется админский токен."
        )
    return provided


class RateLimiter:
    """Простой лимитер в памяти.

    Хватает на один процесс. При переходе на несколько воркеров заменить
    на Redis — отмечено в docs/PHASE1.md.
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
