#!/usr/bin/env python
"""Собирает калькулятор для сайта в один HTML-файл.

Файл ни от чего не зависит: считает в браузере, заявку отправляет в
WhatsApp. Его можно просто положить на хостинг garantlc.ru рядом с
остальными страницами — сервер не нужен.

    ./.venv/bin/python site/build.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "dist" / "calculator.html"


def widget_markup() -> str:
    html = (ROOT / "widget" / "index.html").read_text(encoding="utf-8")
    match = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    if not match:
        raise SystemExit("widget/index.html: не найден <body>")
    body = re.sub(r'\s*<script src="calculator\.js"></script>', "", match.group(1))
    return body.strip()


def main() -> int:
    template = (ROOT / "site" / "shell.html").read_text(encoding="utf-8")
    styles = "\n".join([
        (ROOT / "widget" / "calculator.css").read_text(encoding="utf-8"),
        # Из демо-обёртки берём только стили печатной формы.
        (ROOT / "demo" / "shell.css").read_text(encoding="utf-8"),
    ])
    legal = json.loads((ROOT / "backend" / "config" / "legal-config.json").read_text(encoding="utf-8"))

    parts = {
        "{{STYLES}}": styles,
        "{{WIDGET}}": widget_markup(),
        "{{CONFIG}}": (ROOT / "site" / "config.js").read_text(encoding="utf-8"),
        "{{ENGINE}}": (ROOT / "demo" / "engine.js").read_text(encoding="utf-8"),
        "{{LEGAL}}": json.dumps(legal, ensure_ascii=False, indent=2),
        "{{SITE_GLUE}}": (ROOT / "site" / "site-glue.js").read_text(encoding="utf-8"),
        "{{GLUE}}": (ROOT / "demo" / "glue.js").read_text(encoding="utf-8"),
        "{{CALCULATOR}}": (ROOT / "widget" / "calculator.js").read_text(encoding="utf-8"),
    }

    page = template
    for token, value in parts.items():
        if token not in page:
            raise SystemExit(f"В шаблоне нет метки {token}")
        if "</script" in value and token != "{{WIDGET}}":
            raise SystemExit(f"{token} содержит '</script' — при инлайне это сломает страницу")
        page = page.replace(token, value)

    leftovers = re.findall(r"\{\{[A-Z_]+\}\}", page)
    if leftovers:
        raise SystemExit(f"Незаполненные метки: {leftovers}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Готово: {OUT.relative_to(ROOT)} ({len(page.encode('utf-8')) / 1024:.0f} КБ)")
    if "79001234567" in page:
        print("ВНИМАНИЕ: в site/config.js остался номер-заглушка — впишите свой WhatsApp.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
