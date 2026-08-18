"""Чтение переменных окружения.

В .env переменную часто оставляют пустой (`DATABASE_URL=`), подразумевая
«взять значение по умолчанию». os.getenv так не считает: он вернёт пустую
строку, и приложение упадёт на старте уже на сервере. Поэтому пустое
значение здесь приравнено к отсутствующему.
"""

from __future__ import annotations

import os


def env(name: str, default: str = "") -> str:
    return (os.getenv(name) or "").strip() or default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]
