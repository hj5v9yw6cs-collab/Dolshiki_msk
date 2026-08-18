"""Точка входа API.

Фаза 1: калькулятор неустойки, приём заявок, админка юридического конфига.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import admin, auth, calc, cases, documents, leads
from .site.routes import router as site_router
from .env import env, env_list
from .core.legal_config import LegalConfigError, store
from .db import init_db

logging.basicConfig(level=env("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

WIDGET_DIR = Path(__file__).resolve().parents[2] / "widget"
ADMIN_DIR = Path(__file__).resolve().parents[2] / "admin"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        config = store.get()
        logger.info(
            "Юридический конфиг загружен: версия %s от %s", config.version, config.updated_at
        )
        pending = config.review_warnings(
            ["day_count", "rates", "delay_penalty", "defects_penalty", "consumer_penalty"]
        )
        for warning in pending:
            logger.warning("%s", warning)
    except LegalConfigError as exc:
        # Падаем на старте, а не в момент расчёта у клиента.
        logger.error("Юридический конфиг невалиден: %s", exc)
        raise
    yield


app = FastAPI(
    title="Калькулятор неустойки 214-ФЗ и приём заявок",
    version="1.0.0",
    description=(
        "Фаза 1. Расчёт неустойки по 214-ФЗ с учётом мораториев и изменений ключевой ставки, "
        "приём заявок с сайта, редактирование юридических параметров."
    ),
    lifespan=lifespan,
)

# Виджет встраивается на dolshikirf.ru, поэтому кросс-доменные запросы нужны.
# Список доменов задаётся переменной CORS_ORIGINS, по умолчанию — только локальная разработка.
origins = env_list("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(calc.router)
app.include_router(leads.router)
app.include_router(cases.router)
app.include_router(documents.router)
app.include_router(admin.router)

if WIDGET_DIR.exists():
    app.mount("/widget", StaticFiles(directory=WIDGET_DIR), name="widget")

# Рабочий интерфейс для сотрудников.
if ADMIN_DIR.exists():
    app.mount("/app", StaticFiles(directory=ADMIN_DIR, html=True), name="admin")


@app.get("/health", tags=["Служебное"])
def health() -> dict:
    config = store.get()
    return {"status": "ok", "config_version": config.version}


@app.get("/embed.js", include_in_schema=False)
def embed_script():
    """Короткий адрес для вставки на сайт: <script src=".../embed.js"></script>"""
    return FileResponse(WIDGET_DIR / "embed.js", media_type="application/javascript")


# Публичный сайт подключается последним: у него есть общий маршрут /{slug},
# и он перехватил бы адреса API и кабинета, если бы шёл раньше.
app.include_router(site_router)
