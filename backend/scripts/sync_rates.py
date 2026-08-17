#!/usr/bin/env python
"""Синхронизация ключевой ставки ЦБ. Ставится в cron раз в сутки:

    0 6 * * *  cd /opt/dolshiki/backend && ./.venv/bin/python scripts/sync_rates.py

Скрипт не падает при недоступности cbr.ru — записывает причину в состояние
синхронизации, а API помечает ставку как устаревшую.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.cbr import sync_rates  # noqa: E402
from app.core.legal_config import store  # noqa: E402

if __name__ == "__main__":
    result = sync_rates(store)
    if result.get("synced"):
        print(f"Синхронизация выполнена, добавлено записей: {result['added']}")
    else:
        print(f"Синхронизация не выполнена: {result.get('reason')}")
        sys.exit(1)
