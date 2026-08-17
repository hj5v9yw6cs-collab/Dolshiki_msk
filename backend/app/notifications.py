"""Уведомления о новых заявках.

Пока один канал — Telegram. Если токен не задан, уведомление тихо
пропускается: заявка уже сохранена в базе и не теряется.
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _escape(text: str | None) -> str:
    return (text or "").replace("<", "&lt;").replace(">", "&gt;").replace("&", "&amp;")


def build_message(lead) -> str:
    lines = [
        "<b>Новая заявка</b>",
        f"Имя: {_escape(lead.name)}",
        f"Телефон: {_escape(lead.phone)}",
    ]
    if lead.email:
        lines.append(f"Почта: {_escape(lead.email)}")
    lines.append(f"Тема: {_escape(lead.topic)}")
    if lead.region:
        lines.append(f"Регион: {_escape(lead.region)}")
    if lead.project:
        lines.append(f"Объект: {_escape(lead.project)}")
    if lead.comment:
        lines.append(f"Комментарий: {_escape(lead.comment)}")
    if lead.calculation and lead.calculation.result:
        lines.append(f"Расчёт: {lead.calculation.result.get('total_display', '')} ₽")
    if lead.page_url:
        lines.append(f"Страница: {_escape(lead.page_url)}")
    return "\n".join(lines)


def notify_new_lead(lead) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.info("Telegram не настроен — уведомление о заявке %s пропущено.", lead.id)
        return False

    try:
        response = httpx.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": build_message(lead), "parse_mode": "HTML"},
            timeout=10.0,
        )
        if response.status_code != 200:
            logger.warning("Telegram ответил %s: %s", response.status_code, response.text[:200])
            return False
        return True
    except httpx.HTTPError as exc:
        # Заявка уже в базе — падать из-за уведомления нельзя.
        logger.warning("Не удалось отправить уведомление в Telegram: %s", exc)
        return False
