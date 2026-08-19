"""Общие зависимости API: доступ, роли и ограничение частоты."""

from __future__ import annotations

import hmac
import ipaddress
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Deque, Dict, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..core.security import token_fingerprint
from ..env import env
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

    # Ключей в памяти столько, сколько разных адресов постучалось. Без
    # уборки один поток запросов с разных адресов раздувает словарь, а
    # памяти на сервере 1 ГБ.
    MAX_KEYS = 10_000

    def check(self, key: str) -> None:
        now = time.monotonic()
        self._forget_expired(now)

        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много запросов. Попробуйте через несколько минут.",
            )
        hits.append(now)

    def reset(self) -> None:
        """Забыть все попытки. Нужен тестам и ручному снятию блокировки."""
        self._hits.clear()

    def _forget_expired(self, now: float) -> None:
        if len(self._hits) < self.MAX_KEYS:
            return
        for key in [k for k, hits in self._hits.items() if not hits or now - hits[-1] > self.window]:
            del self._hits[key]


# Адреса, с которых заголовку X-Forwarded-For можно верить: приложение
# стоит за Caddy во внутренней сети Docker, и других промежуточных узлов нет.
TRUSTED_PROXY_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
)


def _is_trusted_proxy(host: str) -> bool:
    try:
        return any(ipaddress.ip_address(host) in network for network in TRUSTED_PROXY_NETWORKS)
    except ValueError:
        return False


def client_ip(request: Request) -> str:
    """Адрес клиента с оглядкой на то, кто его сообщил.

    X-Forwarded-For приходит от браузера ровно так же, как от прокси, и
    подделать его может кто угодно. Раньше брался первый адрес из списка —
    то есть тот, который прислал сам клиент: достаточно менять его в каждом
    запросе, чтобы ограничение попыток входа перестало работать вовсе.

    Caddy дописывает настоящий адрес в конец списка, поэтому берём
    последний и только если запрос действительно пришёл от прокси во
    внутренней сети. Иначе — адрес соединения, подделать который нельзя.
    """
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and _is_trusted_proxy(peer):
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return peer


lead_limiter = RateLimiter(limit=5, window_seconds=600)
calc_limiter = RateLimiter(limit=60, window_seconds=600)
MIN_ADMIN_TOKEN_LENGTH = 24

login_limiter = RateLimiter(limit=10, window_seconds=300)
# Ограничение по адресу не спасает от подбора с многих адресов, а учётных
# записей в системе четыре: считаем попытки ещё и по самому логину.
login_account_limiter = RateLimiter(limit=10, window_seconds=300)


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

    admin_token = env("ADMIN_TOKEN")
    # compare_digest вместо == : обычное сравнение строк выходит на первом
    # несовпавшем символе, и по времени ответа токен подбирается посимвольно.
    # Короткий токен не принимается вовсе: он равносилен паролю руководителя
    # без ограничения попыток, и оставленная в .env заготовка не должна
    # молча стать рабочим ключом.
    if admin_token and len(admin_token) >= MIN_ADMIN_TOKEN_LENGTH:
        if hmac.compare_digest(token, admin_token):
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
