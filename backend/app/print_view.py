"""Печатная форма расчёта — приложение к исковому заявлению.

Отдаём HTML со стилями для печати: браузер сохраняет его в PDF без
дополнительных библиотек и без проблем с кириллическими шрифтами.
Генерация .docx-приложения появится в Фазе 4 вместе с шаблонами исков.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any, Dict, List

STYLES = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
  font-family: 'Times New Roman', Georgia, serif;
  font-size: 12pt; line-height: 1.45; color: #111; background: #fff;
  max-width: 190mm; margin: 0 auto; padding: 12mm 8mm;
}
h1 { font-size: 15pt; text-align: center; margin: 0 0 4mm; }
.subtitle { text-align: center; font-size: 11pt; color: #444; margin-bottom: 8mm; }
table { width: 100%; border-collapse: collapse; margin: 4mm 0 6mm; font-size: 10.5pt; }
th, td { border: 1px solid #333; padding: 2mm 2.5mm; vertical-align: top; }
th { background: #f0f0f0; font-weight: bold; text-align: center; }
td.num { text-align: right; white-space: nowrap; }
td.center { text-align: center; white-space: nowrap; }
tr.total td { font-weight: bold; background: #f7f7f7; }
h2 { font-size: 12pt; margin: 6mm 0 2mm; }
.note { font-size: 10pt; color: #333; margin: 1.5mm 0; }
.warning {
  border-left: 3px solid #b00; background: #fff4f4; padding: 3mm 4mm;
  font-size: 10pt; margin: 4mm 0;
}
.disclaimer { margin-top: 8mm; font-size: 10pt; font-style: italic; color: #444;
  border-top: 1px solid #999; padding-top: 3mm; }
.meta { font-size: 9.5pt; color: #666; margin-top: 6mm; }
@media print {
  body { padding: 0; }
  .no-print { display: none; }
  table { page-break-inside: auto; }
  tr { page-break-inside: avoid; }
}
.no-print { text-align: center; margin-bottom: 6mm; }
.no-print button {
  font: inherit; padding: 2mm 6mm; cursor: pointer;
  border: 1px solid #333; background: #fff; border-radius: 3px;
}
"""

MODE_TITLES = {
    "delay": "Расчёт неустойки за нарушение срока передачи объекта долевого строительства",
    "defects": "Расчёт стоимости устранения недостатков и неустойки",
}


def _rows_segments(segments: List[Dict[str, Any]]) -> str:
    rows = []
    for index, segment in enumerate(segments, start=1):
        capped = ""
        if segment.get("rate_before_cap"):
            capped = (
                f"<br><span class='note'>ставка ограничена с "
                f"{escape(str(segment['rate_before_cap']))}% — "
                f"{escape(segment.get('cap_basis') or '')}</span>"
            )
        rows.append(
            "<tr>"
            f"<td class='center'>{index}</td>"
            f"<td class='center'>{escape(segment['start_display'])} — {escape(segment['end_display'])}</td>"
            f"<td class='center'>{segment['days']}</td>"
            f"<td class='center'>{escape(segment['rate_display'])}{capped}</td>"
            f"<td>{escape(segment['formula'])}</td>"
            f"<td class='num'>{escape(segment['amount_display'])}</td>"
            "</tr>"
        )
    return "".join(rows)


def _rows_excluded(excluded: List[Dict[str, Any]]) -> str:
    rows = []
    for item in excluded:
        rows.append(
            "<tr>"
            f"<td class='center'>{escape(item['start_display'])} — {escape(item['end_display'])}</td>"
            f"<td class='center'>{item['days']}</td>"
            f"<td>{escape(item['basis'])}</td>"
            "</tr>"
        )
    return "".join(rows)


def _rows_lines(lines: List[Dict[str, Any]], total_display: str) -> str:
    rows = []
    for line in lines:
        note = f"<br><span class='note'>{escape(line['note'])}</span>" if line.get("note") else ""
        rows.append(
            "<tr>"
            f"<td>{escape(line['title'])}{note}</td>"
            f"<td>{escape(line.get('basis') or '')}</td>"
            f"<td class='num'>{escape(line['amount_display'])}</td>"
            "</tr>"
        )
    rows.append(
        "<tr class='total'><td colspan='2'>ИТОГО к взысканию</td>"
        f"<td class='num'>{escape(total_display)} ₽</td></tr>"
    )
    return "".join(rows)


def render_print_page(result: Dict[str, Any], created_at: datetime | None = None) -> str:
    title = MODE_TITLES.get(result.get("mode", ""), "Расчёт")
    period = result.get("period") or {}
    segments = result.get("segments") or []
    excluded = result.get("excluded") or []
    warnings = result.get("warnings") or []
    notes = result.get("notes") or []

    parts: List[str] = [
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{escape(title)}</title><style>{STYLES}</style></head><body>",
        "<div class='no-print'><button onclick='window.print()'>Печать / сохранить в PDF</button></div>",
        f"<h1>{escape(title)}</h1>",
    ]

    if period.get("start_display"):
        parts.append(
            f"<p class='subtitle'>Период просрочки: {escape(period['start_display'])} — "
            f"{escape(period['end_display'])}, засчитано "
            f"{escape(period.get('days_display', ''))}</p>"
        )
    else:
        parts.append("<p class='subtitle'>Период просрочки отсутствует</p>")

    if warnings:
        parts.append(
            "<div class='warning'><b>Внимание.</b> "
            + "<br>".join(escape(warning) for warning in warnings)
            + "<br>Проверьте юридические параметры расчёта перед подачей документа в суд.</div>"
        )

    if segments:
        parts.append("<h2>Расчёт по периодам</h2>")
        parts.append(
            "<table><thead><tr>"
            "<th style='width:6%'>№</th><th style='width:22%'>Период</th>"
            "<th style='width:8%'>Дней</th><th style='width:12%'>Ставка</th>"
            "<th>Расчёт</th><th style='width:16%'>Сумма, ₽</th>"
            "</tr></thead><tbody>" + _rows_segments(segments) + "</tbody></table>"
        )
        parts.append(
            f"<p class='note'>Порядок определения ставки: {escape(result.get('rate_mode_title', ''))}.</p>"
        )

    if excluded:
        parts.append("<h2>Периоды, исключённые из расчёта</h2>")
        parts.append(
            "<table><thead><tr><th style='width:30%'>Период</th>"
            "<th style='width:12%'>Дней</th><th>Основание</th></tr></thead><tbody>"
            + _rows_excluded(excluded)
            + "</tbody></table>"
        )

    parts.append("<h2>Состав требований</h2>")
    parts.append(
        "<table><thead><tr><th>Требование</th><th style='width:32%'>Основание</th>"
        "<th style='width:18%'>Сумма, ₽</th></tr></thead><tbody>"
        + _rows_lines(result.get("lines") or [], result.get("total_display", "0,00"))
        + "</tbody></table>"
    )

    for note in notes:
        parts.append(f"<p class='note'>{escape(note)}</p>")

    if result.get("disclaimer"):
        parts.append(f"<p class='disclaimer'>{escape(result['disclaimer'])}</p>")

    stamp = (created_at or datetime.now()).strftime("%d.%m.%Y %H:%M")
    parts.append(
        f"<p class='meta'>Расчёт сформирован автоматически {escape(stamp)}. "
        f"Версия юридического конфига: {escape(str(result.get('config_version', '')))}. "
        "Документ является черновиком и требует проверки юристом.</p>"
    )
    parts.append("</body></html>")
    return "".join(parts)
