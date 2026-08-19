#!/usr/bin/env python
"""Утренняя сводка в Telegram: что просрочено и что горит.

Ставится в cron на будни:

    0 6 * * 1-5  cd /opt/dolshiki/deploy && docker compose exec -T app \
                 python scripts/daily_digest.py

Сроки по делам считает та же функция, что и кабинет, — расхождения между
сводкой и карточкой быть не может. Если сводке нечего сказать, сообщение
не отправляется: молчание должно означать «всё спокойно», иначе его
перестают читать.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.casework import next_deadline  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Case, Lead  # noqa: E402
from app.notifications import send_message  # noqa: E402

# Ближе этого срока дело попадает в сводку.
SOON_DAYS = 7


def build_digest(cases, new_leads: int, today: date) -> str:
    overdue, soon = [], []

    for case in cases:
        deadline = next_deadline(case, today)
        if deadline is None:
            continue
        line = (
            f"{case.number} · {case.client.full_name if case.client else '—'} · "
            f"{deadline.title} {deadline.due_on.strftime('%d.%m')}"
        )
        if deadline.is_overdue:
            overdue.append((deadline.due_on, line))
        elif deadline.days_left <= SOON_DAYS:
            soon.append((deadline.due_on, line))

    if not overdue and not soon and not new_leads:
        return ""

    lines = [f"<b>Сводка на {today.strftime('%d.%m.%Y')}</b>"]

    if overdue:
        lines.append("")
        lines.append(f"<b>Просрочено ({len(overdue)})</b>")
        lines += [text for _, text in sorted(overdue)]

    if soon:
        lines.append("")
        lines.append(f"<b>На неделе ({len(soon)})</b>")
        lines += [text for _, text in sorted(soon)]

    if new_leads:
        lines.append("")
        lines.append(f"Новых заявок: {new_leads}")

    return "\n".join(lines)


def main() -> int:
    init_db()
    session = SessionLocal()
    try:
        cases = session.scalars(select(Case)).all()
        new_leads = len(session.scalars(select(Lead).where(Lead.status == "new")).all())
        text = build_digest(cases, new_leads, date.today())
    finally:
        session.close()

    if not text:
        print("Сводка пустая — сообщение не отправлено.")
        return 0

    if send_message(text):
        print("Сводка отправлена.")
        return 0

    print("Не удалось отправить сводку: проверьте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
