#!/usr/bin/env python
"""Собирает автономную демо-страницу калькулятора в один HTML-файл.

Берёт настоящие файлы виджета и расчётный конфиг, добавляет JS-ядро и
демо-обёртку. Никаких внешних запросов в результате нет — страницу можно
открыть локально или опубликовать как есть.

    ../.venv/bin/python demo/build_demo.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo" / "dist" / "demo.html"


def widget_markup() -> str:
    """Разметка виджета из widget/index.html — без обвязки страницы."""
    html = (ROOT / "widget" / "index.html").read_text(encoding="utf-8")
    match = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    if not match:
        raise SystemExit("widget/index.html: не найден <body>")
    body = match.group(1)
    # Скрипт подключается отдельно — инлайном в конце собранной страницы.
    body = re.sub(r'\s*<script src="calculator\.js"></script>', "", body)
    return body.strip()


def main() -> int:
    template = (ROOT / "demo" / "shell.html").read_text(encoding="utf-8")
    styles = "\n".join([
        (ROOT / "widget" / "calculator.css").read_text(encoding="utf-8"),
        (ROOT / "demo" / "shell.css").read_text(encoding="utf-8"),
    ])
    config = json.loads((ROOT / "backend" / "config" / "legal-config.json").read_text(encoding="utf-8"))

    page = template
    for token, value in {
        "{{STYLES}}": styles,
        "{{WIDGET}}": widget_markup(),
        "{{ENGINE}}": (ROOT / "demo" / "engine.js").read_text(encoding="utf-8"),
        "{{CONFIG}}": json.dumps(config, ensure_ascii=False, indent=2),
        "{{GLUE}}": (ROOT / "demo" / "glue.js").read_text(encoding="utf-8"),
        "{{CALCULATOR}}": (ROOT / "widget" / "calculator.js").read_text(encoding="utf-8"),
    }.items():
        if token not in page:
            raise SystemExit(f"В шаблоне нет метки {token}")
        page = page.replace(token, value)

    leftovers = re.findall(r"\{\{[A-Z_]+\}\}", page)
    if leftovers:
        raise SystemExit(f"Незаполненные метки: {leftovers}")

    # Закрывающий тег внутри JS разорвал бы <script> раньше времени.
    for name in ("engine.js", "glue.js"):
        if "</script" in (ROOT / "demo" / name).read_text(encoding="utf-8"):
            raise SystemExit(f"{name} содержит '</script' — при инлайне это сломает страницу")
    if "</script" in (ROOT / "widget" / "calculator.js").read_text(encoding="utf-8"):
        raise SystemExit("calculator.js содержит '</script' — при инлайне это сломает страницу")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Готово: {OUT.relative_to(ROOT)} ({len(page.encode('utf-8')) / 1024:.0f} КБ)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
